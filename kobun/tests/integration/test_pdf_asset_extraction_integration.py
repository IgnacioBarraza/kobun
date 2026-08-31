"""
Asset extraction over real PDFs, through every layer.

Where the unit tests check the orchestration with a scripted extractor, these
check the part only PyMuPDF can answer: which images a page actually holds, that
the bytes come out unrecompressed, and that a repeated logo is one image and not
one per page. Skipped if PyMuPDF is missing.
"""
import struct
import zlib

import pytest

pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF no instalado")

from kobun.application.dto.extract_assets_request import ExtractAssetsRequest  # noqa: E402
from kobun.application.services.output_directory_resolver import (  # noqa: E402
    OutputDirectoryResolver,
)
from kobun.application.use_cases.extract_assets_use_case import (  # noqa: E402
    ExtractAssetsUseCase,
)
from kobun.domain.pdf.exceptions.encrypted_pdf_exception import (  # noqa: E402
    EncryptedPdfException,
)
from kobun.domain.pdf.exceptions.invalid_pdf_exception import InvalidPdfException  # noqa: E402
from kobun.domain.pdf.exceptions.pdf_not_found_exception import (  # noqa: E402
    PdfNotFoundException,
)
from kobun.domain.pdf.services.asset_extractor_service import (  # noqa: E402
    AssetExtractorService,
)
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode  # noqa: E402
from kobun.domain.pdf.value_objects.overwrite_policy import OverwritePolicy  # noqa: E402
from kobun.domain.pdf.value_objects.page_selection import PageSelection  # noqa: E402
from kobun.infrastructure.filesystem.local_file_storage import LocalFileStorage  # noqa: E402
from kobun.infrastructure.pdf_engine.pdf_document_opener import PdfDocumentOpener  # noqa: E402
from kobun.infrastructure.pdf_engine.pdf_engine_adapter import PdfEngineAdapter  # noqa: E402
from kobun.infrastructure.repositories.pdf_asset_extractor_impl import (  # noqa: E402
    PyMuPdfAssetExtractor,
)
from kobun.infrastructure.repositories.pdf_repository_impl import PyMuPdfRepository  # noqa: E402

FIGURES = ExtractionMode.FIGURES
IMAGES = ExtractionMode.EMBEDDED_IMAGES
RASTER = ExtractionMode.PAGE_RASTER


def png_bytes(width: int, height: int, colour: tuple) -> bytes:
    """
    A minimal valid PNG, built by hand so the test does not need Pillow and so
    the exact bytes are known: that is what proves nothing was recompressed.
    """
    raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


LOGO = png_bytes(40, 40, (200, 30, 30))
SPACER = png_bytes(1, 1, (0, 0, 0))


def jpeg_bytes(width: int, height: int, colour: tuple) -> bytes:
    """
    A JPEG, produced through the engine because writing one by hand is not
    worth it. It matters that the figure is JPEG: that is the case where the
    stored stream *is* a file format and comes back byte for byte.
    """
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height))
    pixmap.set_rect(pixmap.irect, colour)

    return pixmap.tobytes("jpeg")


FIGURE = jpeg_bytes(160, 120, (30, 110, 200))
FIGURE_SIDE = (160, 120)
LOGO_SIDE = (40, 40)


def png_dimensions(data: bytes) -> tuple:
    """Width and height straight out of the IHDR, to identify a file without Pillow."""
    return struct.unpack(">II", data[16:24])


def dimensions_of(path) -> tuple:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG"):
        return png_dimensions(data)

    doc = pymupdf.open(stream=data, filetype="jpeg")
    try:
        page = doc.load_page(0)
        return int(page.rect.width), int(page.rect.height)
    finally:
        doc.close()


@pytest.fixture
def source_pdf(tmp_path):
    """
    Twelve pages that cover the cases that matter:

    - a logo on every page, stored once and referenced twelve times
    - a 1x1 spacer on every page, which nobody wants in their folder
    - a real figure on pages 3 and 8
    - page 6 with a vector drawing and no stored image at all
    """
    path = tmp_path / "libro.pdf"
    doc = pymupdf.open()

    for number in range(1, 13):
        page = doc.new_page()
        page.insert_text((72, 120), f"PAGINA {number}", fontsize=30)
        page.insert_image(pymupdf.Rect(430, 40, 470, 80), stream=LOGO)
        page.insert_image(pymupdf.Rect(20, 20, 21, 21), stream=SPACER)

        if number in (3, 8):
            page.insert_image(pymupdf.Rect(72, 200, 232, 320), stream=FIGURE)

        if number == 6:
            page.draw_rect(pymupdf.Rect(72, 200, 300, 340), color=(0, 0, 1), fill=(0.8, 0.9, 1))

    doc.set_metadata({"title": "Libro Original", "author": "Ignacio"})
    doc.save(path)
    doc.close()

    return path


@pytest.fixture
def vector_pdf(tmp_path):
    """
    A report whose figures are drawn, not stored: the case where "extract the
    images" used to come back empty.

    Deliberately includes the things that ruin naive detection: a page border, a
    rule under the heading, a body paragraph beside the chart, and axis labels
    that sit *outside* the drawing's bounds.
    """
    path = tmp_path / "informe.pdf"
    doc = pymupdf.open()

    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(30, 30, 565, 812), color=(0.9, 0.9, 0.9))
    page.insert_text((72, 80), "Informe anual", fontsize=20)
    page.draw_line(pymupdf.Point(72, 95), pymupdf.Point(520, 95))
    page.insert_text((72, 130), "Parrafo de cuerpo que no es parte de la figura.", fontsize=10)
    for index, (height, label) in enumerate(((60, "Q1"), (110, "Q2"), (85, "Q3"), (140, "Q4"))):
        x = 90 + index * 50
        page.draw_rect(
            pymupdf.Rect(x, 300 - height, x + 34, 300), fill=(0.2, 0.4, 0.8), color=(0, 0, 0)
        )
        page.insert_text((x + 8, 313), label, fontsize=9)
    page.draw_line(pymupdf.Point(85, 300), pymupdf.Point(300, 300))
    page.draw_line(pymupdf.Point(85, 300), pymupdf.Point(85, 150))

    page2 = doc.new_page()
    page2.insert_text((72, 80), "Diagramas", fontsize=20)
    page2.draw_circle(pymupdf.Point(150, 250), 60, color=(1, 0, 0), fill=(1, 0.9, 0.9))
    page2.draw_rect(pymupdf.Rect(350, 180, 500, 320), color=(0, 0.5, 0), fill=(0.9, 1, 0.9))

    page3 = doc.new_page()
    page3.insert_text((72, 80), "Solo texto", fontsize=20)
    page3.insert_text((72, 120), "Esta pagina no tiene ninguna figura.", fontsize=11)

    doc.save(path)
    doc.close()

    return path


@pytest.fixture
def use_case():
    storage = LocalFileStorage()
    engine = PdfEngineAdapter()
    opener = PdfDocumentOpener(engine)

    return ExtractAssetsUseCase(
        pdf_repository=PyMuPdfRepository(engine, opener),
        asset_extractor=PyMuPdfAssetExtractor(engine, opener),
        asset_service=AssetExtractorService(),
        output_directory_resolver=OutputDirectoryResolver(storage),
        file_storage=storage,
    )


def extract(use_case, path, pages, mode=IMAGES, **kwargs):
    return use_case.execute(
        ExtractAssetsRequest(path, PageSelection.parse(pages), mode, **kwargs)
    )


# =========================
# Imágenes embebidas
# =========================

def test_the_images_of_a_page_are_written_to_disk(use_case, source_pdf):
    response = extract(use_case, source_pdf, "3")

    assert response.asset_count >= 1
    assert all(path.exists() and path.stat().st_size > 0 for path in response.files)


def test_a_stored_jpeg_comes_back_byte_for_byte(use_case, source_pdf):
    """
    The strongest form of "no recompression": a JPEG is a file format the PDF
    stores as-is, so what comes out is the identical stream that went in.
    """
    response = extract(use_case, source_pdf, "3")
    written = {path.read_bytes() for path in response.files}

    assert FIGURE in written


def test_an_image_the_pdf_stores_raw_comes_back_as_a_lossless_png(use_case, source_pdf):
    """
    The logo is kept as flate-compressed samples, which is not a file format.
    The engine wraps it into PNG, so the bytes differ from the original file
    while the image does not: same dimensions, no lossy step.
    """
    response = extract(use_case, source_pdf, "1")
    logo = next(path for path in response.files if dimensions_of(path) == LOGO_SIDE)

    assert logo.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert logo.suffix == ".png"
    assert logo.read_bytes() != LOGO, "Se reserializa; lo que se conserva son los píxeles"


def test_an_image_repeated_on_every_page_comes_out_once(use_case, source_pdf):
    """
    The logo is one stored object referenced twelve times. Yielding it per page
    would bury the real figures under twelve copies of a header.
    """
    response = extract(use_case, source_pdf, "1-12")
    logos = [path for path in response.files if dimensions_of(path) == LOGO_SIDE]

    assert len(logos) == 1


def test_invisible_spacers_never_reach_the_folder(use_case, source_pdf):
    response = extract(use_case, source_pdf, "1-12")

    assert all(path.read_bytes() != SPACER for path in response.files)


def test_the_files_are_named_after_the_page_they_came_from(use_case, source_pdf):
    response = extract(use_case, source_pdf, "3")

    assert any("_p003_" in path.name for path in response.files)


def test_the_folder_holds_exactly_what_was_reported(use_case, source_pdf):
    response = extract(use_case, source_pdf, "1-12")

    on_disk = sorted(path.name for path in response.output_directory.iterdir())

    assert on_disk == sorted(path.name for path in response.files)


def test_a_page_with_only_vectors_yields_no_images(use_case, source_pdf, tmp_path):
    """
    The caveat the UI warns about, verified: a vector drawing is not a stored
    image, and this is the case the raster mode exists for.
    """
    response = extract(use_case, source_pdf, "6", output_directory=tmp_path / "solo_6")
    figures = [path for path in response.files if dimensions_of(path) != LOGO_SIDE]

    assert figures == [], "El dibujo vectorial de la página 6 no es una imagen guardada"


def test_a_document_with_no_images_at_all_finds_nothing(use_case, tmp_path):
    path = tmp_path / "solo_texto.pdf"
    doc = pymupdf.open()
    for number in range(1, 4):
        page = doc.new_page()
        page.insert_text((72, 100), f"solo texto {number}", fontsize=24)
        page.draw_circle(pymupdf.Point(300, 400), 80, color=(1, 0, 0))
    doc.save(path)
    doc.close()

    response = extract(use_case, path, "1-3")

    assert response.found_nothing is True
    assert not response.output_directory.exists(), "No debe quedar una carpeta vacía"


# =========================
# Páginas rasterizadas
# =========================

def test_every_selected_page_becomes_one_png(use_case, source_pdf):
    response = extract(use_case, source_pdf, "2,5-7", mode=RASTER, dpi=72)

    assert [path.name for path in response.files] == [
        "libro_p002.png",
        "libro_p005.png",
        "libro_p006.png",
        "libro_p007.png",
    ]


def test_a_rendered_page_is_a_real_png(use_case, source_pdf):
    response = extract(use_case, source_pdf, "1", mode=RASTER, dpi=72)

    assert response.files[0].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_a_vector_only_page_does_come_out_rendered(use_case, source_pdf):
    """The answer the UI points at when an image extraction finds nothing."""
    response = extract(use_case, source_pdf, "6", mode=RASTER, dpi=72)

    assert response.asset_count == 1
    assert response.files[0].stat().st_size > 0


def test_a_higher_resolution_produces_a_bigger_image(use_case, source_pdf, tmp_path):
    low = extract(use_case, source_pdf, "1", mode=RASTER, dpi=72,
                  output_directory=tmp_path / "baja")
    high = extract(use_case, source_pdf, "1", mode=RASTER, dpi=300,
                   output_directory=tmp_path / "alta")

    assert high.total_size_bytes > low.total_size_bytes


def test_a_discontinuous_selection_keeps_the_document_order(use_case, source_pdf):
    response = extract(use_case, source_pdf, "9,2,5", mode=RASTER, dpi=72)

    assert [path.name for path in response.files] == [
        "libro_p002.png",
        "libro_p005.png",
        "libro_p009.png",
    ]


# =========================
# El PDF de origen
# =========================

def test_the_source_pdf_is_left_untouched(use_case, source_pdf):
    before = source_pdf.read_bytes()

    extract(use_case, source_pdf, "1-12")
    extract(use_case, source_pdf, "1-12", mode=RASTER, dpi=72,
            output_directory=source_pdf.parent / "rasters")

    assert source_pdf.read_bytes() == before


def test_the_source_can_be_extracted_from_twice_in_a_row(use_case, source_pdf, tmp_path):
    """
    The generator holds the document open while it is consumed; if it were not
    closed on the way out, the second run would fail on Windows.
    """
    first = extract(use_case, source_pdf, "3", output_directory=tmp_path / "uno")
    second = extract(use_case, source_pdf, "3", output_directory=tmp_path / "dos")

    assert first.asset_count == second.asset_count


def test_an_encrypted_pdf_is_rejected_the_same_way_as_for_splitting(use_case, tmp_path):
    path = tmp_path / "protegido.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="d", user_pw="s")
    doc.close()

    with pytest.raises(EncryptedPdfException, match="contraseña"):
        extract(use_case, path, "1")


def test_a_corrupt_file_is_rejected(use_case, tmp_path):
    path = tmp_path / "roto.pdf"
    path.write_bytes(b"no soy un pdf")

    with pytest.raises(InvalidPdfException):
        extract(use_case, path, "1")


def test_a_missing_file_is_rejected(use_case, tmp_path):
    with pytest.raises(PdfNotFoundException):
        extract(use_case, tmp_path / "fantasma.pdf", "1")


# =========================
# Destino
# =========================

def test_two_extractions_collect_in_one_folder(use_case, source_pdf, tmp_path):
    """
    The behaviour the folder-per-run design got wrong: choosing a folder and
    accumulating in it, over real PDFs and real files.
    """
    target = tmp_path / "mis figuras"

    first = extract(use_case, source_pdf, "3", output_directory=target)
    second = extract(use_case, source_pdf, "8", output_directory=target)

    assert first.output_directory == second.output_directory == target
    on_disk = sorted(path.name for path in target.iterdir())
    assert len(on_disk) == first.asset_count + second.asset_count
    assert any("_p003_" in name for name in on_disk)
    assert any("_p008_" in name for name in on_disk)


def test_a_folder_with_someone_else_s_files_is_used_without_touching_them(
    use_case, source_pdf, tmp_path
):
    target = tmp_path / "mis figuras"
    target.mkdir()
    (target / "ajeno.txt").write_bytes(b"no me toques")

    response = extract(use_case, source_pdf, "3", output_directory=target)

    assert response.output_directory == target
    assert (target / "ajeno.txt").read_bytes() == b"no me toques"


def test_re_extracting_the_same_pages_replaces_instead_of_duplicating(
    use_case, source_pdf, tmp_path
):
    target = tmp_path / "salida"

    first = extract(use_case, source_pdf, "3", output_directory=target)
    second = extract(use_case, source_pdf, "3", output_directory=target)

    assert sorted(p.name for p in target.iterdir()) == sorted(
        p.name for p in first.files
    )
    assert second.replaced_count == second.asset_count


def test_the_rename_policy_keeps_the_earlier_files(use_case, source_pdf, tmp_path):
    target = tmp_path / "salida"

    first = extract(use_case, source_pdf, "3", output_directory=target)
    extract(
        use_case,
        source_pdf,
        "3",
        output_directory=target,
        policy=OverwritePolicy.RENAME,
    )

    assert len(list(target.iterdir())) == first.asset_count * 2


def test_the_fail_policy_refuses_to_touch_an_existing_file(use_case, source_pdf, tmp_path):
    from kobun.domain.pdf.exceptions.invalid_output_path_exception import (
        InvalidOutputPathException,
    )

    target = tmp_path / "salida"
    first = extract(use_case, source_pdf, "3", output_directory=target)
    contents = {path.name: path.read_bytes() for path in first.files}

    with pytest.raises(InvalidOutputPathException):
        extract(
            use_case,
            source_pdf,
            "3",
            output_directory=target,
            policy=OverwritePolicy.FAIL,
        )

    for name, data in contents.items():
        assert (target / name).read_bytes() == data


def test_a_file_sitting_at_the_destination_path_is_rejected(use_case, source_pdf, tmp_path):
    from kobun.domain.pdf.exceptions.invalid_output_path_exception import (
        InvalidOutputPathException,
    )

    taken = tmp_path / "no_soy_carpeta"
    taken.write_bytes(b"archivo")

    with pytest.raises(InvalidOutputPathException, match="no puede usarse como carpeta"):
        extract(use_case, source_pdf, "3", output_directory=taken)
# =========================
# Figuras vectoriales
# =========================

def test_a_vector_chart_is_extracted_even_with_no_stored_image(use_case, vector_pdf):
    """
    The complaint this mode answers: the PDF has no embedded image, and a
    screenshot of the whole page is not the figure.
    """
    response = extract(use_case, vector_pdf, "1", mode=FIGURES, dpi=100)

    assert response.asset_count == 1
    assert response.files[0].name == "informe_p001_fig01.png"
    assert response.files[0].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_the_crop_is_the_figure_and_not_the_page(use_case, vector_pdf):
    """
    Rendered at the same resolution, a figure has to come out clearly smaller
    than its page — otherwise nothing was cropped.
    """
    figure = extract(use_case, vector_pdf, "1", mode=FIGURES, dpi=100)
    whole = extract(
        use_case,
        vector_pdf,
        "1",
        mode=RASTER,
        dpi=100,
        output_directory=vector_pdf.parent / "paginas",
    )

    assert dimensions_of(figure.files[0])[0] < dimensions_of(whole.files[0])[0]
    assert dimensions_of(figure.files[0])[1] < dimensions_of(whole.files[0])[1]


def test_two_separate_diagrams_come_out_as_two_figures(use_case, vector_pdf):
    response = extract(use_case, vector_pdf, "2", mode=FIGURES, dpi=100)

    assert [path.name for path in response.files] == [
        "informe_p002_fig01.png",
        "informe_p002_fig02.png",
    ]


def test_the_page_border_does_not_swallow_the_page(use_case, vector_pdf):
    """
    Without filtering it, the border merges with everything it encloses and the
    "figure" is the whole page. Verified through the size of what came out.
    """
    response = extract(use_case, vector_pdf, "1", mode=FIGURES, dpi=100)
    width, height = dimensions_of(response.files[0])

    assert width < 560
    assert height < 500


def test_the_rule_under_the_heading_is_not_a_figure(use_case, vector_pdf):
    response = extract(use_case, vector_pdf, "1", mode=FIGURES, dpi=100)

    assert response.asset_count == 1, "La línea del título no es una figura"


def test_a_page_with_only_text_yields_nothing(use_case, vector_pdf):
    response = extract(use_case, vector_pdf, "3", mode=FIGURES, dpi=100)

    assert response.found_nothing is True


def test_a_higher_resolution_gives_a_bigger_figure(use_case, vector_pdf, tmp_path):
    low = extract(use_case, vector_pdf, "1", mode=FIGURES, dpi=72,
                  output_directory=tmp_path / "baja")
    high = extract(use_case, vector_pdf, "1", mode=FIGURES, dpi=200,
                   output_directory=tmp_path / "alta")

    assert dimensions_of(high.files[0])[0] > dimensions_of(low.files[0])[0]


def test_the_figures_mode_also_returns_the_stored_images(use_case, source_pdf):
    """
    "Give me the pictures, whatever they are made of": on a PDF that does store
    images, they come out as the stored bytes and not as renders.
    """
    response = extract(use_case, source_pdf, "3", mode=FIGURES, dpi=100)
    written = {path.read_bytes() for path in response.files}

    assert any("_img" in path.name for path in response.files)
    assert FIGURE in written


def test_the_strict_mode_still_returns_nothing_for_vector_art(use_case, vector_pdf):
    """
    The two modes stay honestly different: EMBEDDED_IMAGES promises only stored
    data, and a vector chart is not that.
    """
    response = extract(use_case, vector_pdf, "1", mode=IMAGES)

    assert response.found_nothing is True


def test_a_framed_photo_is_not_handed_back_twice(use_case, tmp_path):
    """
    A border drawn around a photo produces a vector region over it. Cropping
    that would return a rendered copy of a picture already extracted at full
    quality.
    """
    path = tmp_path / "enmarcada.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    box = pymupdf.Rect(72, 200, 272, 350)
    page.insert_image(box, stream=FIGURE)
    page.draw_rect(box + (-2, -2, 2, 2), color=(0, 0, 0))
    doc.save(path)
    doc.close()

    response = extract(use_case, path, "1", mode=FIGURES, dpi=100)

    # A stored JPEG keeps its format, so the name ends in .jpeg: what matters is
    # that there is exactly one file and it is the stored one, not a render.
    assert [p.name for p in response.files] == ["enmarcada_p001_img01.jpeg"]
