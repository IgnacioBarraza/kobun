from pathlib import Path
from typing import List, Optional, Set

from PySide6.QtCore import QObject, QThreadPool, Signal

from kobun.application.dto.extract_assets_request import ExtractAssetsRequest
from kobun.application.dto.split_pdf_request import SplitPdfRequest
from kobun.application.interfaces.file_storage import FileStorage
from kobun.application.use_cases.extract_assets_use_case import ExtractAssetsUseCase
from kobun.application.use_cases.list_history_use_case import ListHistoryUseCase
from kobun.application.use_cases.load_pdf_use_case import LoadPdfUseCase
from kobun.application.use_cases.record_extraction_use_case import RecordExtractionUseCase
from kobun.application.use_cases.record_split_use_case import RecordSplitUseCase
from kobun.application.use_cases.split_pdf_use_case import SplitPdfUseCase
from kobun.domain.pdf.entities.pdf_document import PdfDocument
from kobun.domain.pdf.services.asset_extractor_service import DEFAULT_DPI
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode
from kobun.domain.pdf.value_objects.overwrite_policy import OverwritePolicy
from kobun.domain.pdf.value_objects.page_selection import PageSelection
from kobun.presentation.qt.workers import Worker


class PdfViewModel(QObject):
    """
    The screen's state and the bridge towards the use cases.

    The window knows no use case: it connects this object's signals and calls
    its methods. That leaves the screen's logic testable without instantiating
    widgets.
    """

    document_loaded = Signal(object)
    load_failed = Signal(object)

    split_started = Signal()
    split_succeeded = Signal(object)
    split_failed = Signal(object)

    extract_started = Signal()
    extract_succeeded = Signal(object)
    extract_failed = Signal(object)

    history_changed = Signal(list)
    history_failed = Signal(object)

    busy_changed = Signal(bool)

    def __init__(
        self,
        load_use_case: LoadPdfUseCase,
        split_use_case: SplitPdfUseCase,
        record_use_case: RecordSplitUseCase,
        list_history_use_case: ListHistoryUseCase,
        file_storage: FileStorage,
        extract_use_case: ExtractAssetsUseCase,
        record_extraction_use_case: RecordExtractionUseCase,
        thread_pool: Optional[QThreadPool] = None,
    ):
        super().__init__()
        self._load_use_case = load_use_case
        self._split_use_case = split_use_case
        self._record_use_case = record_use_case
        self._list_history_use_case = list_history_use_case
        self._file_storage = file_storage
        self._extract_use_case = extract_use_case
        self._record_extraction_use_case = record_extraction_use_case
        self._thread_pool = thread_pool or QThreadPool.globalInstance()

        self._document: Optional[PdfDocument] = None
        self._busy = False

        # Without this reference the workers can be collected before emitting
        # their signals, and the operation is lost silently.
        self._running: Set[Worker] = set()

    # =========================
    # State
    # =========================

    @property
    def document(self) -> Optional[PdfDocument]:
        return self._document

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def has_document(self) -> bool:
        return self._document is not None

    def suggested_output_path(self, selection: PageSelection) -> Optional[Path]:
        if self._document is None:
            return None

        return self._split_use_case.suggest_output_path(self._document, selection)

    def suggested_output_directory(self, mode: ExtractionMode) -> Optional[Path]:
        """
        Independent of the page selection on purpose: one folder collects every
        extraction from this document, so it can be suggested as soon as the PDF
        is open.
        """
        if self._document is None:
            return None

        return self._extract_use_case.suggest_output_directory(self._document, mode)

    # =========================
    # Actions
    # =========================

    def load_document(self, file_path: Path) -> None:
        """
        Opens a PDF off the UI thread. The result arrives through
        `document_loaded` or `load_failed`.
        """
        if self._busy:
            return

        self._set_busy(True)
        self._submit(
            lambda: self._load_use_case.execute(Path(file_path)),
            on_success=self._on_document_loaded,
            on_failure=self._on_load_failed,
        )

    def split(
        self,
        selection: PageSelection,
        output_path: Optional[Path] = None,
        policy: OverwritePolicy = OverwritePolicy.FAIL,
    ) -> None:
        """
        Splits the loaded document. The result arrives through
        `split_succeeded` or `split_failed`.
        """
        if self._busy or self._document is None:
            return

        request = SplitPdfRequest(
            input_path=self._document.storage_path,
            selection=selection,
            output_path=output_path,
            policy=policy,
        )

        self._set_busy(True)
        self.split_started.emit()
        self._submit(
            lambda: self._split_use_case.execute(request),
            on_success=self._on_split_succeeded,
            on_failure=self._on_split_failed,
        )

    def extract_assets(
        self,
        selection: PageSelection,
        mode: ExtractionMode = ExtractionMode.FIGURES,
        output_directory: Optional[Path] = None,
        dpi: int = DEFAULT_DPI,
        policy: OverwritePolicy = OverwritePolicy.OVERWRITE,
    ) -> None:
        """
        Extracts images from the loaded document. The result arrives through
        `extract_succeeded` or `extract_failed`.

        An extraction that found nothing arrives through `extract_succeeded`
        with an empty response: it is an outcome, not a failure.
        """
        if self._busy or self._document is None:
            return

        request = ExtractAssetsRequest(
            input_path=self._document.storage_path,
            selection=selection,
            mode=mode,
            output_directory=output_directory,
            dpi=dpi,
            policy=policy,
        )

        self._set_busy(True)
        self.extract_started.emit()
        self._submit(
            lambda: self._extract_use_case.execute(request),
            on_success=self._on_extract_succeeded,
            on_failure=self._on_extract_failed,
        )

    def refresh_history(self, limit: Optional[int] = None) -> None:
        """
        Reloads the history. It is fast —reading a small JSON— so it runs on
        the main thread and avoids flicker in the list.
        """
        try:
            self.history_changed.emit(self._list_history_use_case.execute(limit))
        except Exception as error:
            self.history_failed.emit(error)

    def open_export(self, path: Path) -> None:
        """
        Opens an exported PDF with the system viewer.

        :raises FileOpenException: If the file is no longer available.
        """
        self._file_storage.open_in_default_app(Path(path))

    def reveal_export(self, path: Path) -> None:
        """
        Shows an export in the system's file manager.

        :raises FileOpenException: If the path is no longer available.
        """
        self._file_storage.reveal_in_file_manager(Path(path))

    # =========================
    # Worker callbacks
    # =========================

    def _on_document_loaded(self, document: PdfDocument) -> None:
        self._document = document
        self._set_busy(False)
        self.document_loaded.emit(document)

    def _on_load_failed(self, error: Exception) -> None:
        self._document = None
        self._set_busy(False)
        self.load_failed.emit(error)

    def _on_split_succeeded(self, response) -> None:
        self._set_busy(False)
        self.split_succeeded.emit(response)

        # Recording is separate from splitting: if the history cannot be
        # written, the PDF is already on disk and the operation succeeded.
        try:
            self._record_use_case.execute(response)
        except Exception as error:
            self.history_failed.emit(error)

        self.refresh_history()

    def _on_split_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self.split_failed.emit(error)

    def _on_extract_succeeded(self, response) -> None:
        self._set_busy(False)
        self.extract_succeeded.emit(response)

        # Same split of responsibilities as after a split: the files are on
        # disk, so a history that cannot be written is a minor problem and not a
        # failed export.
        try:
            self._record_extraction_use_case.execute(response)
        except Exception as error:
            self.history_failed.emit(error)

        self.refresh_history()

    def _on_extract_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self.extract_failed.emit(error)

    # =========================
    # Internals
    # =========================

    def _submit(self, operation, on_success, on_failure) -> None:
        worker = Worker(operation)
        self._running.add(worker)

        def release(callback):
            def handler(value):
                self._running.discard(worker)
                callback(value)

            return handler

        worker.signals.finished.connect(release(on_success))
        worker.signals.failed.connect(release(on_failure))

        self._thread_pool.start(worker)

    def _set_busy(self, busy: bool) -> None:
        if self._busy == busy:
            return

        self._busy = busy
        self.busy_changed.emit(busy)
