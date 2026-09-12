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
from kobun.application.use_cases.render_page_preview_use_case import (
    DEFAULT_PREVIEW_WIDTH,
    RenderPagePreviewUseCase,
)
from kobun.application.use_cases.split_pdf_use_case import SplitPdfUseCase
from kobun.domain.pdf.entities.pdf_document import PdfDocument
from kobun.domain.pdf.services.asset_extractor_service import DEFAULT_DPI
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode
from kobun.domain.pdf.value_objects.overwrite_policy import OverwritePolicy
from kobun.domain.pdf.value_objects.page_selection import PageSelection
from kobun.presentation.preview_cache import PreviewCache
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

    preview_page_changed = Signal(int)
    """Which page the preview is on. Emitted before the render starts, so the
    panel can label itself while the image is still being painted."""

    preview_ready = Signal(object)
    preview_failed = Signal(object)

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
        preview_use_case: RenderPagePreviewUseCase,
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
        self._preview_use_case = preview_use_case

        self._preview_cache = PreviewCache()
        self._preview_page: Optional[int] = None

        # The width every render is produced at. It follows the largest view
        # that is open —the thumbnail scales a big render down happily, while the
        # reverse looks blurry— so one render serves both and the enlarged window
        # is not paying for a second pass over every page.
        self._preview_width = DEFAULT_PREVIEW_WIDTH

        # Bumped on every request so a slow render cannot overwrite a newer one.
        # Typing "1-5,10-15" moves the preview five times, and the page that ends
        # up on screen has to be the last one asked for, not the last one to
        # finish painting.
        self._preview_token = 0
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

    @property
    def page_count(self) -> int:
        """Pages in the loaded document, or zero when none is open."""
        if self._document is None or self._document.page_count is None:
            return 0

        return self._document.page_count

    @property
    def preview_page(self) -> Optional[int]:
        """Which page the preview is showing, or None before a document is open."""
        return self._preview_page

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

    def show_preview_page(self, page_number: int) -> None:
        """
        Moves the preview to a page and has it painted.

        The page is clamped to the document, so the panel's arrows can stay dumb
        and ask for "one more" at the last page without having to know where the
        end is.

        A page already rendered at the current width comes straight back from the
        cache —no worker, no flicker— which is what makes flipping through a
        chapter feel immediate.
        """
        if self._document is None:
            return

        page_number = max(1, min(int(page_number), self.page_count))

        if page_number != self._preview_page:
            self._preview_page = page_number
            self.preview_page_changed.emit(page_number)

        self._request_preview(page_number)

    def move_preview(self, offset: int) -> None:
        """
        Steps the preview forwards or backwards, from wherever it is.
        """
        if self._document is None or self._preview_page is None:
            return

        self.show_preview_page(self._preview_page + offset)

    def set_preview_width(self, target_width: int) -> None:
        """
        Renders at a new size from now on, and repaints the current page.

        Called when the enlarged view opens and closes: it wants a render several
        times wider, and going back to the thumbnail's width keeps the next
        keystroke-driven jump cheap.
        """
        if target_width == self._preview_width:
            return

        self._preview_width = target_width

        if self._preview_page is not None:
            self._request_preview(self._preview_page)

    def _request_preview(self, page_number: int) -> None:
        cached = self._preview_cache.get(page_number, self._preview_width)
        if cached is not None:
            self.preview_ready.emit(cached)
            return

        self._preview_token += 1
        token = self._preview_token
        document = self._document
        width = self._preview_width

        self._submit(
            lambda: self._preview_use_case.execute(document, page_number, width),
            on_success=lambda preview: self._on_preview_ready(preview, token, width),
            on_failure=lambda error: self._on_preview_failed(error, token),
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

        # The cached pages belong to the file that was open before, and a render
        # still in flight belongs to it too.
        self._preview_cache.clear()
        self._preview_page = None
        self._preview_token += 1

        self.document_loaded.emit(document)

    def _on_load_failed(self, error: Exception) -> None:
        self._document = None
        self._set_busy(False)

        self._preview_cache.clear()
        self._preview_page = None
        self._preview_token += 1

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

    def _on_preview_ready(self, preview, token: int, target_width: int) -> None:
        """
        Results arriving out of order are dropped: only the newest request owns
        the panel. The render is still cached, since it cost the same to make and
        the user may well come back to that page.
        """
        self._preview_cache.put(preview, target_width)

        if token == self._preview_token:
            self.preview_ready.emit(preview)

    def _on_preview_failed(self, error: Exception, token: int) -> None:
        if token == self._preview_token:
            self.preview_failed.emit(error)

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
