from typing import Optional

from kobun.application.dto.extract_assets_response import ExtractAssetsResponse
from kobun.application.interfaces.history_repository import HistoryRepository
from kobun.domain.history.entities.export_record import ExportRecord
from kobun.domain.history.value_objects.export_kind import ExportKind
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode

# Both image-producing modes are one kind in the history: either way what was
# left behind is a folder of images, and which files were copied and which were
# rendered is already legible in their names.
_KINDS = {
    ExtractionMode.FIGURES: ExportKind.IMAGES,
    ExtractionMode.EMBEDDED_IMAGES: ExportKind.IMAGES,
    ExtractionMode.PAGE_RASTER: ExportKind.PAGES,
}


class RecordExtractionUseCase:
    """
    Records an asset extraction into the history.

    Separated from ExtractAssetsUseCase for the same reason RecordSplitUseCase
    is separated from the split: the images are already on disk, and a history
    that cannot be written must not turn a finished export into a failure.
    """

    def __init__(self, history_repository: HistoryRepository):
        self._history_repository = history_repository

    def execute(self, response: ExtractAssetsResponse) -> Optional[ExportRecord]:
        """
        :param response: The result returned by ExtractAssetsUseCase.
        :return: The created record, or None when there was nothing to record.

        An extraction that found no images is a real outcome the UI reports,
        but not an export: nothing was produced, so there is no file for the
        user to come back to and the entry would only be noise in the list.
        """
        if response.found_nothing:
            return None

        record = ExportRecord(
            source_path=response.source_path,
            selection=response.selection,
            output_path=response.output_directory,
            page_count=response.pages_requested,
            size_bytes=response.total_size_bytes,
            created_at=response.completed_at,
            kind=_KINDS[response.mode],
            item_count=response.asset_count,
        )

        self._history_repository.add(record)

        return record
