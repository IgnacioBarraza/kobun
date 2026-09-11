import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from kobun.domain.history.entities.export_record import ExportRecord
from kobun.domain.history.value_objects.export_kind import ExportKind
from kobun.domain.pdf.value_objects.page_selection import PageSelection
from kobun.infrastructure.repositories.json_history_repository import (
    SCHEMA_VERSION,
    JsonHistoryRepository,
)

WHEN = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def record(name: str = "book", minutes: int = 0, **overrides) -> ExportRecord:
    defaults = dict(
        source_path=Path(f"/libros/{name}.pdf"),
        selection=PageSelection.parse("1-5"),
        output_path=Path(f"/libros/{name}_1-5.pdf"),
        page_count=5,
        size_bytes=1024,
        created_at=WHEN + timedelta(minutes=minutes),
    )
    return ExportRecord(**{**defaults, **overrides})


@pytest.fixture
def repository(tmp_path):
    return JsonHistoryRepository(tmp_path / "history.json")


def test_empty_history_when_file_does_not_exist(repository):
    assert repository.list_recent() == []


def test_add_creates_the_file_and_its_directory(tmp_path):
    repository = JsonHistoryRepository(tmp_path / "sub" / "dir" / "history.json")

    repository.add(record())

    assert repository.file_path.exists()


def test_records_come_back_newest_first(repository):
    repository.add(record("primero"))
    repository.add(record("segundo"))
    repository.add(record("tercero"))

    nombres = [r.source_filename for r in repository.list_recent()]

    assert nombres == ["tercero.pdf", "segundo.pdf", "primero.pdf"]


def test_limit_returns_only_the_newest(repository):
    for i in range(5):
        repository.add(record(f"doc{i}"))

    assert len(repository.list_recent(limit=2)) == 2
    assert repository.list_recent(limit=2)[0].source_filename == "doc4.pdf"


def test_round_trip_preserves_every_field(repository):
    original = record(title="Libro (1-5)")

    repository.add(original)
    recuperado = repository.list_recent()[0]

    assert recuperado.id == original.id
    assert recuperado.source_path == original.source_path
    assert recuperado.output_path == original.output_path
    assert recuperado.selection == original.selection
    assert recuperado.page_count == original.page_count
    assert recuperado.size_bytes == original.size_bytes
    assert recuperado.created_at == original.created_at
    assert recuperado.title == original.title


def test_round_trip_preserves_discontinuous_selections(repository):
    repository.add(record(selection=PageSelection.parse("1-3,10,20-22")))

    assert str(repository.list_recent()[0].selection) == "1-3,10,20-22"


def test_old_entries_are_dropped_beyond_the_cap(tmp_path):
    repository = JsonHistoryRepository(tmp_path / "history.json", max_entries=3)

    for i in range(6):
        repository.add(record(f"doc{i}"))

    guardados = repository.list_recent()

    assert len(guardados) == 3
    assert [r.source_filename for r in guardados] == ["doc5.pdf", "doc4.pdf", "doc3.pdf"]


def test_remove_deletes_only_the_requested_record(repository):
    first = record("primero")
    second = record("segundo")
    repository.add(first)
    repository.add(second)

    assert repository.remove(first.id) is True
    assert [r.source_filename for r in repository.list_recent()] == ["segundo.pdf"]


def test_remove_reports_when_the_record_is_absent(repository):
    repository.add(record())

    assert repository.remove(uuid4()) is False
    assert len(repository.list_recent()) == 1


def test_clear_empties_the_history(repository):
    repository.add(record())

    repository.clear()

    assert repository.list_recent() == []


def test_clear_is_safe_on_an_empty_history(repository):
    repository.clear()

    assert repository.list_recent() == []


def test_file_uses_a_versioned_schema(repository):
    repository.add(record())

    payload = json.loads(repository.file_path.read_text(encoding="utf-8"))

    assert payload["version"] == SCHEMA_VERSION
    assert len(payload["entries"]) == 1


def test_corrupt_file_is_quarantined_instead_of_crashing(repository):
    repository.file_path.write_text("{ esto no es json", encoding="utf-8")

    assert repository.list_recent() == []
    assert repository.file_path.with_name("history.json.corrupt").exists()


def test_history_keeps_working_after_corruption(repository):
    repository.file_path.write_text("roto", encoding="utf-8")
    repository.list_recent()

    repository.add(record("nuevo"))

    assert [r.source_filename for r in repository.list_recent()] == ["nuevo.pdf"]


def test_a_single_broken_entry_does_not_hide_the_rest(repository):
    repository.add(record("bueno"))

    payload = json.loads(repository.file_path.read_text(encoding="utf-8"))
    payload["entries"].insert(0, {"id": "no-es-un-uuid", "selection": "???"})
    repository.file_path.write_text(json.dumps(payload), encoding="utf-8")

    guardados = repository.list_recent()

    assert [r.source_filename for r in guardados] == ["bueno.pdf"]


def test_entries_that_are_not_objects_are_ignored(repository):
    repository.file_path.write_text(
        json.dumps({"version": SCHEMA_VERSION, "entries": ["texto suelto", 42]}),
        encoding="utf-8",
    )

    assert repository.list_recent() == []


def test_no_temporary_file_is_left_behind(repository):
    repository.add(record())

    sobrantes = list(repository.file_path.parent.glob("*.tmp"))

    assert sobrantes == []


def test_unicode_survives_the_round_trip(repository):
    repository.add(record(title="Análisis jurídico — año 2026"))

    assert repository.list_recent()[0].title == "Análisis jurídico — año 2026"
# =========================
# Migración del esquema
# =========================

def write_version_1(path: Path, entry_overrides: dict = None) -> None:
    """
    A history exactly as version 1 wrote it: no `kind`, no `item_count`. Written
    by hand and not through the repository, because the point is reading what an
    older build left behind.
    """
    entry = {
        "id": str(uuid4()),
        "source_path": "/libros/book.pdf",
        "selection": "1-5,10",
        "output_path": "/libros/book_1-5_10.pdf",
        "page_count": 6,
        "size_bytes": 2048,
        "created_at": WHEN.isoformat(),
        "title": "Libro (1-5,10)",
    }
    entry.update(entry_overrides or {})

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "entries": [entry]}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_the_current_schema_is_version_2(repository):
    repository.add(record())

    payload = json.loads(repository.file_path.read_text(encoding="utf-8"))

    assert payload["version"] == 2 == SCHEMA_VERSION


def test_version_1_entries_are_read_as_single_file_splits(repository):
    write_version_1(repository.file_path)

    entries = repository.list_recent()

    assert len(entries) == 1
    assert entries[0].kind is ExportKind.SPLIT
    assert entries[0].item_count == 1


def test_version_1_entries_keep_every_field_they_had(repository):
    write_version_1(repository.file_path)

    entry = repository.list_recent()[0]

    assert entry.output_path == Path("/libros/book_1-5_10.pdf")
    assert str(entry.selection) == "1-5,10"
    assert entry.page_count == 6
    assert entry.title == "Libro (1-5,10)"


def test_an_old_history_is_upgraded_in_place_on_the_next_write(repository):
    write_version_1(repository.file_path)

    repository.add(record("nuevo"))
    payload = json.loads(repository.file_path.read_text(encoding="utf-8"))

    assert payload["version"] == SCHEMA_VERSION
    assert len(payload["entries"]) == 2
    assert all("kind" in entry for entry in payload["entries"])


def test_an_unreadable_kind_drops_only_its_own_entry(repository):
    write_version_1(repository.file_path, {"kind": "tablas"})

    assert repository.list_recent() == []


# =========================
# Extracciones
# =========================

def test_an_extraction_survives_the_round_trip(repository):
    original = record(
        output_path=Path("/libros/book_imagenes_1-5"),
        kind=ExportKind.IMAGES,
        item_count=12,
    )

    repository.add(original)
    stored = repository.list_recent()[0]

    assert stored.kind is ExportKind.IMAGES
    assert stored.item_count == 12
    assert stored.output_path == Path("/libros/book_imagenes_1-5")
    assert stored.outputs_directory is True


def test_both_kinds_coexist_in_one_history(repository):
    repository.add(record("split"))
    repository.add(record("imgs", output_path=Path("/x/imgs"), kind=ExportKind.PAGES, item_count=3))

    kinds = [entry.kind for entry in repository.list_recent()]

    assert kinds == [ExportKind.PAGES, ExportKind.SPLIT]
