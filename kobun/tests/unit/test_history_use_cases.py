from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from uuid import UUID

import pytest

from kobun.application.dto.extract_assets_response import ExtractAssetsResponse
from kobun.application.dto.split_pdf_response import SplitPdfResponse
from kobun.application.interfaces.history_repository import HistoryRepository
from kobun.application.use_cases.list_history_use_case import ListHistoryUseCase
from kobun.application.use_cases.record_extraction_use_case import RecordExtractionUseCase
from kobun.application.use_cases.record_split_use_case import RecordSplitUseCase
from kobun.domain.history.entities.export_record import ExportRecord
from kobun.domain.history.value_objects.export_kind import ExportKind
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode
from kobun.domain.pdf.value_objects.page_selection import PageSelection
from kobun.infrastructure.filesystem.local_file_storage import LocalFileStorage

WHEN = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


class InMemoryHistoryRepository(HistoryRepository):
    def __init__(self, records: List[ExportRecord] = None):
        self.records: List[ExportRecord] = list(records or [])

    def add(self, record: ExportRecord) -> None:
        self.records.insert(0, record)

    def list_recent(self, limit: Optional[int] = None) -> List[ExportRecord]:
        return self.records if limit is None else self.records[:limit]

    def remove(self, record_id: UUID) -> bool:
        restantes = [r for r in self.records if r.id != record_id]
        cambio = len(restantes) != len(self.records)
        self.records = restantes
        return cambio

    def clear(self) -> None:
        self.records = []


def response(**overrides) -> SplitPdfResponse:
    defaults = dict(
        source_path=Path("/libros/book.pdf"),
        selection=PageSelection.parse("1-5,10"),
        output_path=Path("/libros/book_1-5_10.pdf"),
        output_size_bytes=2048,
        page_count=6,
        completed_at=WHEN,
        title="Libro (1-5,10)",
    )
    return SplitPdfResponse(**{**defaults, **overrides})


def record(path: Path, **overrides) -> ExportRecord:
    defaults = dict(
        source_path=Path("/libros/book.pdf"),
        selection=PageSelection.parse("1-5"),
        output_path=path,
        page_count=5,
        size_bytes=1024,
        created_at=WHEN,
    )
    return ExportRecord(**{**defaults, **overrides})


# =========================
# RecordSplitUseCase
# =========================

def test_recording_maps_every_field_of_the_response():
    repository = InMemoryHistoryRepository()
    use_case = RecordSplitUseCase(repository)

    created = use_case.execute(response())

    assert created.source_path == Path("/libros/book.pdf")
    assert created.output_path == Path("/libros/book_1-5_10.pdf")
    assert created.selection == PageSelection.parse("1-5,10")
    assert created.page_count == 6
    assert created.size_bytes == 2048
    assert created.created_at == WHEN
    assert created.title == "Libro (1-5,10)"


def test_recording_stores_the_record():
    repository = InMemoryHistoryRepository()

    created = RecordSplitUseCase(repository).execute(response())

    assert repository.records == [created]


def test_recording_uses_the_completion_time_not_the_current_time():
    """The history must reflect when the split happened, not when it was saved."""
    repository = InMemoryHistoryRepository()

    created = RecordSplitUseCase(repository).execute(response(completed_at=WHEN))

    assert created.created_at == WHEN


def test_each_recording_gets_a_distinct_id():
    repository = InMemoryHistoryRepository()
    use_case = RecordSplitUseCase(repository)

    assert use_case.execute(response()).id != use_case.execute(response()).id


# =========================
# ListHistoryUseCase
# =========================

@pytest.fixture
def listing():
    def _build(records):
        repository = InMemoryHistoryRepository(records)
        return ListHistoryUseCase(repository, LocalFileStorage()), repository

    return _build


def test_listing_marks_existing_files_as_available(listing, tmp_path):
    existing = tmp_path / "existe.pdf"
    existing.write_bytes(b"%PDF")

    use_case, _ = listing([record(existing)])
    entries = use_case.execute()

    assert entries[0].is_available is True


def test_listing_marks_missing_files_as_unavailable(listing, tmp_path):
    use_case, _ = listing([record(tmp_path / "borrado.pdf")])

    entries = use_case.execute()

    assert entries[0].is_available is False


def test_missing_files_are_marked_not_filtered_out(listing, tmp_path):
    """
    Design decision: dropping the entry silently would confuse the user, who
    remembers exporting that file.
    """
    existing = tmp_path / "existe.pdf"
    existing.write_bytes(b"%PDF")

    use_case, _ = listing([record(existing), record(tmp_path / "borrado.pdf")])
    entries = use_case.execute()

    assert len(entries) == 2
    assert [e.is_available for e in entries] == [True, False]


def test_a_directory_at_the_output_path_is_not_available(listing, tmp_path):
    folder = tmp_path / "carpeta.pdf"
    folder.mkdir()

    use_case, _ = listing([record(folder)])

    assert use_case.execute()[0].is_available is False


def test_listing_respects_the_limit(listing, tmp_path):
    use_case, _ = listing([record(tmp_path / f"{i}.pdf") for i in range(5)])

    assert len(use_case.execute(limit=2)) == 2


def test_listing_preserves_repository_order(listing, tmp_path):
    use_case, _ = listing([record(tmp_path / f"{i}.pdf") for i in range(3)])

    entries = use_case.execute()

    assert [e.record.output_filename for e in entries] == ["0.pdf", "1.pdf", "2.pdf"]


def test_empty_history_returns_an_empty_list(listing):
    use_case, _ = listing([])

    assert use_case.execute() == []


def test_entry_string_flags_unavailable_files(listing, tmp_path):
    use_case, _ = listing([record(tmp_path / "borrado.pdf")])

    assert str(use_case.execute()[0]).endswith("(no disponible)")
# =========================
# Registro de extracciones
# =========================

def extraction(**overrides) -> ExtractAssetsResponse:
    defaults = dict(
        source_path=Path("/libros/book.pdf"),
        selection=PageSelection.parse("1-5"),
        mode=ExtractionMode.EMBEDDED_IMAGES,
        output_directory=Path("/libros/book_imagenes_1-5"),
        files=(
            Path("/libros/book_imagenes_1-5/book_p002_img01.png"),
            Path("/libros/book_imagenes_1-5/book_p004_img01.png"),
        ),
        total_size_bytes=4096,
        completed_at=WHEN,
    )
    return ExtractAssetsResponse(**{**defaults, **overrides})


def test_an_extraction_is_recorded_as_its_folder():
    repository = InMemoryHistoryRepository()

    stored = RecordExtractionUseCase(repository).execute(extraction())

    assert stored.output_path == Path("/libros/book_imagenes_1-5")
    assert stored.kind is ExportKind.IMAGES
    assert stored.item_count == 2
    assert stored.size_bytes == 4096
    assert repository.records == [stored]


def test_the_recorded_page_count_is_what_was_asked_for():
    """
    Not the number of files: three images can come from one page, and the
    history's "pages" column is about the selection.
    """
    repository = InMemoryHistoryRepository()

    stored = RecordExtractionUseCase(repository).execute(
        extraction(selection=PageSelection.parse("1-5,10"))
    )

    assert stored.page_count == 6


def test_the_raster_mode_is_recorded_as_a_different_kind():
    repository = InMemoryHistoryRepository()

    stored = RecordExtractionUseCase(repository).execute(
        extraction(mode=ExtractionMode.PAGE_RASTER)
    )

    assert stored.kind is ExportKind.PAGES


def test_an_extraction_that_found_nothing_is_not_recorded():
    """
    Nothing was produced, so there is no file for the user to come back to and
    the entry would only be noise in the list.
    """
    repository = InMemoryHistoryRepository()

    assert RecordExtractionUseCase(repository).execute(
        extraction(files=(), total_size_bytes=0)
    ) is None
    assert repository.records == []


def test_an_extraction_folder_that_exists_is_available(tmp_path):
    folder = tmp_path / "book_imagenes_1-5"
    folder.mkdir()
    repository = InMemoryHistoryRepository([
        ExportRecord(
            source_path=Path("/libros/book.pdf"),
            selection=PageSelection.parse("1-5"),
            output_path=folder,
            page_count=5,
            size_bytes=1024,
            created_at=WHEN,
            kind=ExportKind.IMAGES,
            item_count=4,
        )
    ])

    entries = ListHistoryUseCase(repository, LocalFileStorage()).execute()

    assert entries[0].is_available is True


def test_a_deleted_extraction_folder_is_flagged(tmp_path):
    repository = InMemoryHistoryRepository([
        ExportRecord(
            source_path=Path("/libros/book.pdf"),
            selection=PageSelection.parse("1-5"),
            output_path=tmp_path / "borrada",
            page_count=5,
            size_bytes=1024,
            created_at=WHEN,
            kind=ExportKind.IMAGES,
            item_count=4,
        )
    ])

    entries = ListHistoryUseCase(repository, LocalFileStorage()).execute()

    assert entries[0].is_available is False


def test_a_file_where_an_extraction_folder_should_be_is_not_available(tmp_path):
    """The shape has to match: a file is not the folder the entry claims to be."""
    impostor = tmp_path / "book_imagenes_1-5"
    impostor.write_bytes(b"no soy una carpeta")
    repository = InMemoryHistoryRepository([
        ExportRecord(
            source_path=Path("/libros/book.pdf"),
            selection=PageSelection.parse("1-5"),
            output_path=impostor,
            page_count=5,
            size_bytes=1024,
            created_at=WHEN,
            kind=ExportKind.IMAGES,
            item_count=4,
        )
    ])

    entries = ListHistoryUseCase(repository, LocalFileStorage()).execute()

    assert entries[0].is_available is False
@pytest.mark.parametrize("mode", list(ExtractionMode))
def test_every_extraction_mode_maps_to_a_history_kind(mode):
    """
    A mode missing from the mapping is a KeyError at the end of a finished
    extraction —the files are already written— reported to the user as an
    unexpected error. That is exactly how adding the figures mode broke it, so
    the check is over the enum rather than over a list written by hand.
    """
    repository = InMemoryHistoryRepository()

    stored = RecordExtractionUseCase(repository).execute(extraction(mode=mode))

    assert stored is not None
    assert stored.kind in tuple(ExportKind)


def test_the_figures_mode_is_recorded_as_images():
    """
    Both image-producing modes are one kind: either way the folder holds images,
    and which were copied and which were rendered is legible in their names.
    """
    repository = InMemoryHistoryRepository()

    stored = RecordExtractionUseCase(repository).execute(
        extraction(mode=ExtractionMode.FIGURES)
    )

    assert stored.kind is ExportKind.IMAGES
