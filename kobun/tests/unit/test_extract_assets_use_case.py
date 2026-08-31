from pathlib import Path
from typing import Iterator, List, Optional

import pytest

from kobun.application.dto.extract_assets_request import ExtractAssetsRequest
from kobun.application.dto.extracted_asset import ExtractedAsset
from kobun.application.interfaces.pdf_asset_extractor import PdfAssetExtractor
from kobun.application.interfaces.pdf_repository import PdfRepository
from kobun.application.services.output_directory_resolver import OutputDirectoryResolver
from kobun.application.use_cases.extract_assets_use_case import ExtractAssetsUseCase
from kobun.domain.pdf.entities.pdf_document import PdfDocument, PdfProcessingStatus
from kobun.domain.pdf.exceptions.invalid_extraction_exception import InvalidExtractionException
from kobun.domain.pdf.exceptions.invalid_output_path_exception import InvalidOutputPathException
from kobun.domain.pdf.exceptions.invalid_page_range_exception import InvalidPageRangeException
from kobun.domain.pdf.services.asset_extractor_service import AssetExtractorService
from kobun.domain.pdf.value_objects.asset_origin import AssetOrigin
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode
from kobun.domain.pdf.value_objects.overwrite_policy import OverwritePolicy
from kobun.domain.pdf.value_objects.page_selection import PageSelection
from kobun.infrastructure.filesystem.local_file_storage import LocalFileStorage

FIGURES = ExtractionMode.FIGURES
IMAGES = ExtractionMode.EMBEDDED_IMAGES
RASTER = ExtractionMode.PAGE_RASTER

EMBEDDED = AssetOrigin.EMBEDDED
FIGURE = AssetOrigin.FIGURE
PAGE = AssetOrigin.PAGE


def asset(
    page: int,
    sequence: int = 1,
    extension: str = "png",
    size: int = 64,
    side: int = 100,
    origin: AssetOrigin = EMBEDDED,
):
    return ExtractedAsset(
        page_number=page,
        origin=origin,
        sequence=sequence,
        extension=extension,
        data=b"x" * size,
        width=side,
        height=side,
    )


def rendered_page(page: int, size: int = 64):
    return asset(page, origin=PAGE, size=size)


def figure(page: int, sequence: int = 1, size: int = 64, side: int = 400):
    return asset(page, sequence=sequence, size=size, side=side, origin=FIGURE)


class FakePdfRepository(PdfRepository):
    """Only `open_document` matters here: the extraction goes through the other port."""

    def __init__(self, source: PdfDocument):
        self._source = source

    def open_document(self, file_path: Path) -> PdfDocument:
        """
        Hands back the same entity, reset to UPLOADED.

        The real repository builds a **fresh** PdfDocument from the file on every
        open, so a second extraction always starts from UPLOADED. Returning a
        used instance would make the entity refuse to start processing again —
        an artefact of the double, not of the use case. The instance is shared
        rather than rebuilt so a test can still inspect the status it ended in.
        """
        self._source.status = PdfProcessingStatus.UPLOADED

        return self._source

    def close_document(self, document) -> None: ...

    def get_page_count(self, document) -> int: ...

    def extract_metadata(self, document): ...

    def extract_text(self, document, page_number: int) -> str: ...

    def split_single_page(self, src_doc, output_doc, page_index): ...

    def split_page_range(self, src_doc, output_doc, page_range): ...

    def split_page_selection(self, src_doc, output_doc, selection, metadata=None): ...

    def merge_pdfs(self, first_doc, second_doc, output_doc): ...

    def extract_pages(self, document, pages, output_doc): ...


class FakeAssetExtractor(PdfAssetExtractor):
    """
    Yields a scripted list of assets and records how it was called, so the use
    case's orchestration can be checked without PyMuPDF.
    """

    def __init__(
        self,
        embedded: List[ExtractedAsset] = None,
        renders: List[ExtractedAsset] = None,
        figures: List[ExtractedAsset] = None,
    ):
        self._embedded = embedded or []
        self._renders = renders or []
        self._figures = figures or []
        self.embedded_calls = 0
        self.render_calls = 0
        self.figure_calls = 0
        self.received_dpi: Optional[int] = None
        self.consumed = 0

    def _stream(self, items) -> Iterator[ExtractedAsset]:
        for item in items:
            self.consumed += 1
            yield item

    def iter_embedded_images(self, document, selection) -> Iterator[ExtractedAsset]:
        self.embedded_calls += 1
        return self._stream(self._embedded)

    def iter_page_renders(self, document, selection, dpi) -> Iterator[ExtractedAsset]:
        self.render_calls += 1
        self.received_dpi = dpi
        return self._stream(self._renders)

    def iter_figures(self, document, selection, dpi) -> Iterator[ExtractedAsset]:
        self.figure_calls += 1
        self.received_dpi = dpi
        return self._stream(self._figures)


@pytest.fixture
def scenario(make_pdf_document):
    def _build(embedded=None, renders=None, figures=None, page_count: int = 20):
        source = make_pdf_document(filename="libro.pdf", page_count=page_count)
        extractor = FakeAssetExtractor(embedded=embedded, renders=renders, figures=figures)
        storage = LocalFileStorage()

        use_case = ExtractAssetsUseCase(
            pdf_repository=FakePdfRepository(source),
            asset_extractor=extractor,
            asset_service=AssetExtractorService(),
            output_directory_resolver=OutputDirectoryResolver(storage),
            file_storage=storage,
        )
        return use_case, extractor, source

    return _build


# =========================
# Camino feliz
# =========================

def test_assets_are_written_with_their_domain_names(scenario):
    use_case, _, source = scenario(embedded=[asset(3), asset(3, sequence=2), asset(7)])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1-10"), IMAGES)
    )

    assert [path.name for path in response.files] == [
        "libro_p003_img01.png",
        "libro_p003_img02.png",
        "libro_p007_img01.png",
    ]
    assert all(path.exists() for path in response.files)


def test_the_default_folder_sits_next_to_the_source(scenario):
    use_case, _, source = scenario(embedded=[asset(1)])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), IMAGES)
    )

    assert response.output_directory == source.storage_path.parent / "libro_imagenes"


def test_the_response_reports_what_was_produced(scenario):
    use_case, _, source = scenario(embedded=[asset(1, size=100), asset(2, size=50)])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1-2"), IMAGES)
    )

    assert response.asset_count == 2
    assert response.total_size_bytes == 150
    assert response.found_nothing is False
    assert response.mode is IMAGES
    assert response.completed_at.tzinfo is not None


def test_the_bytes_reach_disk_untouched(scenario):
    """The point of extracting is getting the original data, not a re-encoding."""
    use_case, _, source = scenario(embedded=[asset(1, size=321)])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), IMAGES)
    )

    assert response.files[0].read_bytes() == b"x" * 321


def test_the_source_ends_marked_as_processed(scenario):
    use_case, _, source = scenario(embedded=[asset(1)])

    use_case.execute(ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), IMAGES))

    assert source.status == PdfProcessingStatus.PROCESSED


# =========================
# Modos
# =========================

def test_the_raster_mode_goes_through_the_other_extractor_method(scenario):
    use_case, extractor, source = scenario(renders=[rendered_page(1), rendered_page(2)])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1-2"), RASTER, dpi=200)
    )

    assert extractor.render_calls == 1
    assert extractor.embedded_calls == 0
    assert extractor.received_dpi == 200
    assert [path.name for path in response.files] == ["libro_p001.png", "libro_p002.png"]


def test_the_mode_survives_arriving_as_text(scenario):
    """It comes from a Qt combo box as a plain string."""
    use_case, extractor, source = scenario(renders=[rendered_page(1)])

    use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), "page_raster")
    )

    assert extractor.render_calls == 1


# =========================
# Filtro de imágenes insignificantes
# =========================

def test_spacers_are_dropped_before_being_written(scenario):
    use_case, _, source = scenario(
        embedded=[asset(1, side=1), asset(1, sequence=2, side=200), asset(1, sequence=3, side=3)]
    )

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), IMAGES)
    )

    assert response.asset_count == 1


def test_names_stay_contiguous_after_filtering(scenario):
    """
    The sequence counts what was kept, so a dropped spacer does not leave a gap
    at img02.
    """
    use_case, _, source = scenario(
        embedded=[asset(4, side=1), asset(4, sequence=2), asset(4, sequence=3)]
    )

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("4"), IMAGES)
    )

    assert [path.name for path in response.files] == [
        "libro_p004_img01.png",
        "libro_p004_img02.png",
    ]


def test_a_rendered_page_is_never_filtered(scenario):
    """The user asked for that page, not for whatever happened to be drawn on it."""
    use_case, _, source = scenario(renders=[rendered_page(1)])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), RASTER)
    )

    assert response.asset_count == 1


# =========================
# Nada para extraer
# =========================

def test_finding_nothing_is_a_response_and_not_an_error(scenario):
    use_case, _, source = scenario(embedded=[])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1-5"), IMAGES)
    )

    assert response.found_nothing is True
    assert response.files == ()
    assert response.total_size_bytes == 0


def test_finding_nothing_leaves_no_empty_folder_behind(scenario):
    """Probing pages for images is normal; each probe must not leave litter."""
    use_case, _, source = scenario(embedded=[])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("7"), IMAGES)
    )

    assert not response.output_directory.exists()
    assert sorted(p.name for p in source.storage_path.parent.iterdir()) == ["libro.pdf"]


def test_a_folder_that_already_had_files_is_not_removed_when_nothing_is_found(scenario):
    use_case, _, source = scenario(embedded=[])
    target = source.storage_path.parent / "mia"
    target.mkdir()
    (target / "ajeno.txt").write_bytes(b"no me toques")

    use_case.execute(
        ExtractAssetsRequest(
            source.storage_path,
            PageSelection.parse("1"),
            IMAGES,
            output_directory=target,
            policy=OverwritePolicy.OVERWRITE,
        )
    )

    assert (target / "ajeno.txt").read_bytes() == b"no me toques"


def test_a_document_with_everything_filtered_out_counts_as_nothing_found(scenario):
    use_case, _, source = scenario(embedded=[asset(1, side=1), asset(2, side=2)])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1-2"), IMAGES)
    )

    assert response.found_nothing is True


# =========================
# Validación y fallas
# =========================

def test_a_selection_past_the_last_page_is_rejected(scenario):
    use_case, extractor, source = scenario(embedded=[asset(1)], page_count=10)

    with pytest.raises(InvalidPageRangeException):
        use_case.execute(
            ExtractAssetsRequest(source.storage_path, PageSelection.parse("9-20"), IMAGES)
        )

    assert extractor.embedded_calls == 0, "No debe abrirse el extractor si el pedido es inválido"


def test_an_impossible_resolution_is_rejected(scenario):
    use_case, _, source = scenario(renders=[rendered_page(1)])

    with pytest.raises(InvalidExtractionException):
        use_case.execute(
            ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), RASTER, dpi=9000)
        )


def test_an_invalid_request_leaves_the_document_untouched(scenario):
    """
    The destination is resolved before the document is marked as processing:
    an operation that never started must not look like one that failed.
    """
    use_case, _, source = scenario(embedded=[asset(1)], page_count=5)

    with pytest.raises(InvalidPageRangeException):
        use_case.execute(
            ExtractAssetsRequest(source.storage_path, PageSelection.parse("9"), IMAGES)
        )

    assert source.status == PdfProcessingStatus.UPLOADED


def test_a_destination_taken_by_a_file_leaves_the_document_untouched(scenario):
    use_case, _, source = scenario(embedded=[asset(1)])
    taken = source.storage_path.parent / "no_soy_carpeta"
    taken.write_bytes(b"x")

    with pytest.raises(InvalidOutputPathException):
        use_case.execute(
            ExtractAssetsRequest(
                source.storage_path, PageSelection.parse("1"), IMAGES, output_directory=taken
            )
        )

    assert source.status == PdfProcessingStatus.UPLOADED


def test_a_failure_while_extracting_marks_the_document_as_failed(scenario, make_pdf_document):
    source = make_pdf_document(filename="libro.pdf", page_count=10)
    storage = LocalFileStorage()

    class ExplodingExtractor(FakeAssetExtractor):
        def iter_embedded_images(self, document, selection):
            raise RuntimeError("engine exploded")
            yield  # pragma: no cover

    use_case = ExtractAssetsUseCase(
        pdf_repository=FakePdfRepository(source),
        asset_extractor=ExplodingExtractor(),
        asset_service=AssetExtractorService(),
        output_directory_resolver=OutputDirectoryResolver(storage),
        file_storage=storage,
    )

    with pytest.raises(RuntimeError, match="engine exploded"):
        use_case.execute(
            ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), IMAGES)
        )

    assert source.status == PdfProcessingStatus.FAILED


# =========================
# Sugerencia de carpeta
# =========================

def test_the_suggested_folder_touches_no_disk(scenario):
    use_case, _, source = scenario()

    suggested = use_case.suggest_output_directory(source, IMAGES)

    assert suggested == source.storage_path.parent / "libro_imagenes"
    assert not suggested.exists()


def test_the_suggested_folder_reflects_the_mode(scenario):
    use_case, _, source = scenario()

    assert use_case.suggest_output_directory(source, FIGURES).name == "libro_figuras"
    assert use_case.suggest_output_directory(source, IMAGES).name == "libro_imagenes"
    assert use_case.suggest_output_directory(source, RASTER).name == "libro_paginas"


def test_the_suggested_folder_can_be_asked_for_elsewhere(scenario, tmp_path):
    use_case, _, source = scenario()

    suggested = use_case.suggest_output_directory(source, IMAGES, parent=tmp_path / "otro")

    assert suggested == tmp_path / "otro" / "libro_imagenes"

# =========================
# Consumo perezoso
# =========================

def test_each_asset_is_written_before_the_next_one_is_asked_for(scenario, make_pdf_document):
    """
    The whole reason the port yields instead of returning a list: a 300 page
    raster at 300 dpi is gigabytes of pixels, and collecting them before the
    first write is the difference between working and dying.

    Checked by having the extractor count the files already on disk each time it
    is asked for another asset. If the use case collected first, every count
    would be zero.
    """
    source = make_pdf_document(filename="libro.pdf", page_count=10)
    storage = LocalFileStorage()
    target = source.storage_path.parent / "salida"
    counts = []

    class WatchingExtractor(FakeAssetExtractor):
        def iter_page_renders(self, document, selection, dpi):
            for page in (1, 2, 3):
                counts.append(len(list(target.iterdir())) if target.is_dir() else 0)
                yield asset(page)

    use_case = ExtractAssetsUseCase(
        pdf_repository=FakePdfRepository(source),
        asset_extractor=WatchingExtractor(),
        asset_service=AssetExtractorService(),
        output_directory_resolver=OutputDirectoryResolver(storage),
        file_storage=storage,
    )

    use_case.execute(
        ExtractAssetsRequest(
            source.storage_path,
            PageSelection.parse("1-3"),
            RASTER,
            output_directory=target,
        )
    )

    assert counts == [0, 1, 2]


def test_a_rejected_request_never_touches_the_extractor(scenario):
    """Laziness also means an invalid request costs no engine work at all."""
    use_case, extractor, source = scenario(renders=[rendered_page(1)], page_count=5)

    with pytest.raises(InvalidExtractionException):
        use_case.execute(
            ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), RASTER, dpi=1)
        )

    assert extractor.consumed == 0
# =========================
# Modo figuras
# =========================

def test_the_figures_mode_goes_through_its_own_extractor_method(scenario):
    use_case, extractor, source = scenario(figures=[figure(1), asset(1)])

    use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), FIGURES, dpi=200)
    )

    assert extractor.figure_calls == 1
    assert extractor.embedded_calls == 0
    assert extractor.render_calls == 0
    assert extractor.received_dpi == 200


def test_the_figures_mode_is_the_default(scenario):
    """It is what people mean by "extract the images"."""
    use_case, extractor, source = scenario(figures=[figure(1)])

    use_case.execute(ExtractAssetsRequest(source.storage_path, PageSelection.parse("1")))

    assert extractor.figure_calls == 1


def test_stored_images_and_rendered_figures_get_different_names(scenario):
    """
    One mode returns both, and a folder where they are indistinguishable hides
    which files are the originals.
    """
    use_case, _, source = scenario(
        figures=[asset(3), asset(3, sequence=2), figure(3), figure(3, sequence=2)]
    )

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("3"), FIGURES)
    )

    assert [path.name for path in response.files] == [
        "libro_p003_img01.png",
        "libro_p003_img02.png",
        "libro_p003_fig01.png",
        "libro_p003_fig02.png",
    ]


def test_the_two_kinds_are_numbered_independently(scenario):
    """A page's first figure is fig01 even if two images came before it."""
    use_case, _, source = scenario(figures=[asset(5), asset(5, sequence=2), figure(5)])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("5"), FIGURES)
    )

    assert response.files[-1].name == "libro_p005_fig01.png"


def test_a_rendered_figure_is_never_dropped_for_being_small(scenario):
    """
    The significance filter exists to drop stored spacers. A rendered figure
    exists because something was found worth rendering, and its pixel size is a
    consequence of the resolution.
    """
    use_case, _, source = scenario(figures=[figure(1, side=4)])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), FIGURES)
    )

    assert response.asset_count == 1


def test_stored_spacers_are_still_dropped_in_the_figures_mode(scenario):
    use_case, _, source = scenario(figures=[asset(1, side=1), figure(1)])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), FIGURES)
    )

    assert [path.name for path in response.files] == ["libro_p001_fig01.png"]


# =========================
# Una carpeta para todo
# =========================

def test_two_extractions_accumulate_in_one_folder(scenario, tmp_path):
    """
    The complaint that drove the redesign: picking a folder and collecting
    everything in it has to work, instead of a folder per run.
    """
    use_case, extractor, source = scenario(embedded=[asset(1)])
    target = tmp_path / "mis figuras"

    first = use_case.execute(
        ExtractAssetsRequest(
            source.storage_path, PageSelection.parse("1"), IMAGES, output_directory=target
        )
    )
    extractor._embedded = [asset(9)]
    second = use_case.execute(
        ExtractAssetsRequest(
            source.storage_path, PageSelection.parse("9"), IMAGES, output_directory=target
        )
    )

    assert first.output_directory == second.output_directory == target
    assert sorted(p.name for p in target.iterdir()) == [
        "libro_p001_img01.png",
        "libro_p009_img01.png",
    ]


def test_the_suggested_folder_is_the_same_for_every_selection(scenario):
    use_case, extractor, source = scenario(embedded=[asset(1)])

    first = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), IMAGES)
    )
    extractor._embedded = [asset(9)]
    second = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("9"), IMAGES)
    )

    assert first.output_directory == second.output_directory


def test_files_already_in_the_destination_are_left_alone(scenario, tmp_path):
    use_case, _, source = scenario(embedded=[asset(1)])
    target = tmp_path / "mis figuras"
    target.mkdir()
    (target / "ajeno.txt").write_bytes(b"no me toques")

    use_case.execute(
        ExtractAssetsRequest(
            source.storage_path, PageSelection.parse("1"), IMAGES, output_directory=target
        )
    )

    assert (target / "ajeno.txt").read_bytes() == b"no me toques"


# =========================
# Colisiones por archivo
# =========================

def test_re_extracting_the_same_pages_replaces_rather_than_duplicates(scenario, tmp_path):
    """
    The name is derived from the source, the page and the position, so a
    collision means that same asset was extracted before: replacing it is
    regenerating it, and accumulating "_1" copies would be noise.
    """
    use_case, extractor, source = scenario(embedded=[asset(3, size=10)])
    target = tmp_path / "salida"

    use_case.execute(
        ExtractAssetsRequest(
            source.storage_path, PageSelection.parse("3"), IMAGES, output_directory=target
        )
    )
    extractor._embedded = [asset(3, size=99)]
    second = use_case.execute(
        ExtractAssetsRequest(
            source.storage_path, PageSelection.parse("3"), IMAGES, output_directory=target
        )
    )

    assert [p.name for p in target.iterdir()] == ["libro_p003_img01.png"]
    assert second.replaced_count == 1
    assert (target / "libro_p003_img01.png").read_bytes() == b"x" * 99


def test_nothing_replaced_is_reported_as_zero(scenario):
    use_case, _, source = scenario(embedded=[asset(1)])

    response = use_case.execute(
        ExtractAssetsRequest(source.storage_path, PageSelection.parse("1"), IMAGES)
    )

    assert response.replaced_count == 0


def test_the_rename_policy_keeps_both_files(scenario, tmp_path):
    use_case, extractor, source = scenario(embedded=[asset(3, size=10)])
    target = tmp_path / "salida"

    use_case.execute(
        ExtractAssetsRequest(
            source.storage_path,
            PageSelection.parse("3"),
            IMAGES,
            output_directory=target,
            policy=OverwritePolicy.RENAME,
        )
    )
    extractor._embedded = [asset(3, size=99)]
    second = use_case.execute(
        ExtractAssetsRequest(
            source.storage_path,
            PageSelection.parse("3"),
            IMAGES,
            output_directory=target,
            policy=OverwritePolicy.RENAME,
        )
    )

    assert sorted(p.name for p in target.iterdir()) == [
        "libro_p003_img01.png",
        "libro_p003_img01_1.png",
    ]
    assert second.replaced_count == 0


def test_the_fail_policy_reports_the_colliding_file_by_name(scenario, tmp_path):
    use_case, _, source = scenario(embedded=[asset(3)])
    target = tmp_path / "salida"
    target.mkdir()
    (target / "libro_p003_img01.png").write_bytes(b"anterior")

    with pytest.raises(InvalidOutputPathException, match="libro_p003_img01.png"):
        use_case.execute(
            ExtractAssetsRequest(
                source.storage_path,
                PageSelection.parse("3"),
                IMAGES,
                output_directory=target,
                policy=OverwritePolicy.FAIL,
            )
        )

    assert (target / "libro_p003_img01.png").read_bytes() == b"anterior"


def test_a_collision_only_counts_the_same_name(scenario, tmp_path):
    """
    Writing libro_p007_img01.png next to libro_p003_img01.png conflicts with
    nothing, which is why the policy moved off the folder and onto the file.
    """
    use_case, _, source = scenario(embedded=[asset(7)])
    target = tmp_path / "salida"
    target.mkdir()
    (target / "libro_p003_img01.png").write_bytes(b"anterior")

    response = use_case.execute(
        ExtractAssetsRequest(
            source.storage_path,
            PageSelection.parse("7"),
            IMAGES,
            output_directory=target,
            policy=OverwritePolicy.FAIL,
        )
    )

    assert response.asset_count == 1
    assert response.replaced_count == 0
