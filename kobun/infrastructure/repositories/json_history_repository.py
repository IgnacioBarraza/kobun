import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from kobun.application.interfaces.history_repository import HistoryRepository
from kobun.domain.history.entities.export_record import ExportRecord
from kobun.domain.history.value_objects.export_kind import ExportKind
from kobun.domain.pdf.value_objects.page_selection import PageSelection
from kobun.shared.config.app_settings import MAX_HISTORY_ENTRIES

SCHEMA_VERSION = 2
"""Version 2 added `kind` and `item_count`, when the history stopped being
only splits. Entries written by version 1 carry neither and are read as
single-file splits, which is exactly what they were."""


class JsonHistoryRepository(HistoryRepository):
    """
    History persisted in a single JSON file.

    Three decisions that matter:

    - **Atomic writes**: it writes to a temporary file and replaces. If the app
      dies halfway through saving, the previous history stays intact instead of
      becoming a truncated file.
    - **Corruption tolerance**: the history is a convenience, not critical
      data. An unreadable JSON is set aside with a `.corrupt` extension and it
      starts over, rather than stopping the application from launching.
    - **Per-entry tolerance**: a malformed record is dropped on its own,
      without taking the rest of the list down with it.
    """

    def __init__(self, file_path: Path, max_entries: int = MAX_HISTORY_ENTRIES):
        self._file_path = Path(file_path)
        self._max_entries = max_entries

    @property
    def file_path(self) -> Path:
        return self._file_path

    def add(self, record: ExportRecord) -> None:
        records = self._read_all()
        records.insert(0, record)

        self._write_all(records[: self._max_entries])

    def list_recent(self, limit: Optional[int] = None) -> List[ExportRecord]:
        records = self._read_all()

        return records if limit is None else records[:limit]

    def remove(self, record_id: UUID) -> bool:
        records = self._read_all()
        remaining = [record for record in records if record.id != record_id]

        if len(remaining) == len(records):
            return False

        self._write_all(remaining)
        return True

    def clear(self) -> None:
        self._file_path.unlink(missing_ok=True)

    # =========================
    # Persistence
    # =========================

    def _read_all(self) -> List[ExportRecord]:
        if not self._file_path.exists():
            return []

        try:
            with open(self._file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            self._quarantine()
            return []

        entries = payload.get("entries", []) if isinstance(payload, dict) else []

        records = []
        for entry in entries:
            record = self._deserialize(entry)
            if record is not None:
                records.append(record)

        return records

    def _write_all(self, records: List[ExportRecord]) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "version": SCHEMA_VERSION,
            "entries": [self._serialize(record) for record in records],
        }

        # The temporary file goes in the same directory: os.replace is only
        # atomic within one filesystem.
        temporary = self._file_path.with_name(f"{self._file_path.name}.tmp")

        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)

        os.replace(temporary, self._file_path)

    def _quarantine(self) -> None:
        """
        Sets an unreadable history aside instead of deleting it, in case
        someone wants to recover it by hand.
        """
        try:
            self._file_path.replace(self._file_path.with_name(f"{self._file_path.name}.corrupt"))
        except OSError:
            pass

    # =========================
    # Mapping
    # =========================

    @staticmethod
    def _serialize(record: ExportRecord) -> Dict[str, Any]:
        return {
            "id": str(record.id),
            "source_path": str(record.source_path),
            "selection": str(record.selection),
            "output_path": str(record.output_path),
            "page_count": record.page_count,
            "size_bytes": record.size_bytes,
            "created_at": record.created_at.isoformat(),
            "title": record.title,
            "kind": record.kind.value,
            "item_count": record.item_count,
        }

    @staticmethod
    def _deserialize(entry: Any) -> Optional[ExportRecord]:
        if not isinstance(entry, dict):
            return None

        try:
            return ExportRecord(
                id=UUID(entry["id"]),
                source_path=Path(entry["source_path"]),
                selection=PageSelection.parse(entry["selection"]),
                output_path=Path(entry["output_path"]),
                page_count=int(entry["page_count"]),
                size_bytes=int(entry["size_bytes"]),
                created_at=datetime.fromisoformat(entry["created_at"]),
                title=entry.get("title"),
                # Read with `get` and not by subscript: this is the whole
                # migration from version 1, whose entries have no kind and were
                # all splits of a single file.
                kind=ExportKind(entry.get("kind", ExportKind.SPLIT.value)),
                item_count=int(entry.get("item_count", 1)),
            )
        except Exception:
            # A broken entry must not stop the others from being read.
            return None
