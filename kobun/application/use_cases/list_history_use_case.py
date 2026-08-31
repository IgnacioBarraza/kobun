from typing import List, Optional

from kobun.application.dto.history_entry import HistoryEntry
from kobun.application.interfaces.file_storage import FileStorage
from kobun.application.interfaces.history_repository import HistoryRepository


class ListHistoryUseCase:
    """
    Returns the export history, flagging which entries still exist on disk.

    Entries whose file is gone are not filtered out: they are flagged. Dropping
    them silently would confuse the user, who remembers exporting that file;
    seeing it greyed out tells them what happened and leaves the decision to
    them.
    """

    def __init__(self, history_repository: HistoryRepository, file_storage: FileStorage):
        self._history_repository = history_repository
        self._file_storage = file_storage

    def execute(self, limit: Optional[int] = None) -> List[HistoryEntry]:
        """
        :param limit: Maximum number of entries, newest to oldest. None
            returns all of them.
        """
        records = self._history_repository.list_recent(limit)

        return [
            HistoryEntry(record=record, is_available=self._is_available(record))
            for record in records
        ]

    def _is_available(self, record) -> bool:
        """
        Availability is checked against the shape the entry claims to have, not
        merely against existence.

        A split whose PDF was replaced by a folder of the same name is *not*
        available: the document is gone. And an extraction's output is a folder
        from the start, so asking whether it is a file would mark every image
        export as dead the moment it was written.
        """
        if record.outputs_directory:
            return self._file_storage.is_directory(record.output_path)

        return self._file_storage.is_file(record.output_path)
