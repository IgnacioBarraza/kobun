from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem, QMainWindow

from kobun.application.interfaces.history_repository import HistoryRepository
from kobun.application.services.theme_service import ThemeService
from kobun.domain.history.value_objects.export_kind import ExportKind
from kobun.domain.pdf.exceptions.invalid_page_range_exception import InvalidPageRangeException
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode
from kobun.domain.pdf.value_objects.page_selection import PageSelection
from kobun.presentation import error_messages, formatting
from kobun.presentation.qt import dialogs
from kobun.presentation.qt.app_icon import load_app_icon
from kobun.presentation.qt.styles.style_generator import StyleGenerator
from kobun.presentation.qt.windows.ui_main_window import (
    EXTRACT_PAGE,
    HISTORY_PAGE,
    SPLIT_PAGE,
    Ui_MainWindow,
)
from kobun.presentation.viewmodels.pdf_view_model import PdfViewModel

RECORD_ROLE = Qt.ItemDataRole.UserRole

CLEAR_HISTORY_QUESTION = (
    "Se va a borrar todo el historial de exportaciones.\n\n"
    "Los PDFs generados no se tocan; sólo se pierde el registro."
)

OPEN_PDF_TEXT = "Abrir PDF"

# What to tell someone whose extraction came back empty. It names the next thing
# to try instead of just reporting the absence: an image extraction finding
# nothing almost always means the figures are vector drawings, and the other mode
# is exactly the answer to that.
NOTHING_FOUND_HINTS = {
    ExtractionMode.FIGURES: (
        "En esas páginas no hay imágenes guardadas ni figuras dibujadas: "
        "probablemente sean sólo texto. Si igual querés verlas, usá "
        "“Cada página completa, como PNG”."
    ),
    ExtractionMode.EMBEDDED_IMAGES: (
        "Esas páginas no tienen ninguna imagen guardada. Si lo que ves son "
        "gráficos o diagramas, están dibujados con vectores: usá "
        "“Las imágenes y figuras de las páginas”, que los recorta."
    ),
    ExtractionMode.PAGE_RASTER: "No se pudo dibujar ninguna de esas páginas.",
}

# Both image-producing modes are one kind in the history: what they left behind
# is a folder of images either way, and which files were copied and which were
# rendered is already legible in their names.
_EXTRACTION_KINDS = {
    ExtractionMode.FIGURES: ExportKind.IMAGES,
    ExtractionMode.EMBEDDED_IMAGES: ExportKind.IMAGES,
    ExtractionMode.PAGE_RASTER: ExportKind.PAGES,
}


class MainWindow(QMainWindow):
    """
    The main window: it turns interactions into viewmodel calls, and viewmodel
    signals into visible changes.

    It knows no use cases and no domain exceptions beyond asking
    `error_messages` for a message.
    """

    def __init__(
        self,
        view_model: PdfViewModel,
        theme_service: ThemeService,
        history_repository: HistoryRepository,
        show_error: Optional[Callable] = None,
        ask_confirmation: Optional[Callable] = None,
        request_attention: Optional[Callable] = None,
    ):
        super().__init__()
        self._view_model = view_model
        self._theme_service = theme_service
        self._history_repository = history_repository

        # Injectable so which dialog opens can be verified without a modal
        # blocking the test suite waiting for a click.
        self._show_error = show_error or dialogs.show_error
        self._ask_confirmation = ask_confirmation or dialogs.ask_confirmation
        self._request_attention = request_attention or dialogs.request_attention

        # What the last finished export produced, so the result card's buttons
        # have something to act on. Kept here and not read back off the card:
        # the card shows text, it does not hold paths.
        self._last_split_output: Optional[Path] = None
        self._last_extract_output: Optional[Path] = None

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.setWindowIcon(load_app_icon())

        self._populate_themes()
        self.apply_theme(self._theme_service.current())
        self._connect()
        self._view_model.refresh_history()

    # =========================
    # Theme
    # =========================

    def apply_theme(self, theme) -> None:
        self.setStyleSheet(StyleGenerator.generate(theme))

    def select_theme(self, theme_name: str) -> None:
        self.apply_theme(self._theme_service.select(theme_name))

    def _populate_themes(self) -> None:
        """
        Loads the catalogue and preselects the active theme.

        Signals are blocked while the list is built: `setCurrentIndex` would
        emit `currentIndexChanged` and save the preference again during startup,
        for a change the user never made.
        """
        combo = self.ui.combo_theme
        active = self._theme_service.current().name

        combo.blockSignals(True)
        try:
            dark_group = False

            for theme in self._theme_service.available():
                # With many palettes it helps to separate light from dark: the
                # grouping comes from the background's luminance, so a new theme
                # lands in its group on its own.
                if theme.is_dark and not dark_group:
                    if combo.count():
                        combo.insertSeparator(combo.count())
                    dark_group = True

                combo.addItem(theme.display_name, theme.name)

            index = combo.findData(active)
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    def _on_theme_chosen(self, index: int) -> None:
        name = self.ui.combo_theme.itemData(index)

        if name:
            self.select_theme(str(name))

    # =========================
    # Wiring
    # =========================

    def _connect(self) -> None:
        ui = self.ui

        ui.btn_split.clicked.connect(lambda: ui.pages.setCurrentIndex(SPLIT_PAGE))
        ui.btn_extract.clicked.connect(lambda: ui.pages.setCurrentIndex(EXTRACT_PAGE))
        ui.btn_history.clicked.connect(self._show_history)
        ui.combo_theme.currentIndexChanged.connect(self._on_theme_chosen)

        # Both drop areas load through the same handler, so a document opened on
        # either screen is available on both.
        ui.drop_area.file_dropped.connect(self._on_file_chosen)
        ui.extract_drop_area.file_dropped.connect(self._on_file_chosen)

        ui.split_options.selection_changed.connect(self._on_selection_changed)
        ui.btn_process.clicked.connect(self._on_split_requested)

        ui.extract_options.selection_changed.connect(self._on_extract_selection_changed)
        ui.extract_options.mode_changed.connect(self._on_extract_mode_changed)
        ui.btn_extract_process.clicked.connect(self._on_extract_requested)

        ui.split_result.open_requested.connect(self._open_last_split)
        ui.split_result.reveal_requested.connect(self._reveal_last_split)
        ui.extract_result.reveal_requested.connect(self._reveal_last_extraction)

        ui.list_history.itemSelectionChanged.connect(self._on_history_selection_changed)
        ui.list_history.itemDoubleClicked.connect(self._open_history_item)
        ui.btn_open_export.clicked.connect(self._open_selected_export)
        ui.btn_forget_export.clicked.connect(self._forget_selected_export)
        ui.btn_clear_history.clicked.connect(self._clear_history)

        self._view_model.document_loaded.connect(self._on_document_loaded)
        self._view_model.split_succeeded.connect(self._on_split_succeeded)
        self._view_model.extract_succeeded.connect(self._on_extract_succeeded)
        self._view_model.history_changed.connect(self._render_history)
        self._view_model.busy_changed.connect(self._on_busy_changed)

        # What the user asked for and failed interrupts them with a dialog.
        self._view_model.load_failed.connect(self._report_blocking_error)
        self._view_model.split_failed.connect(self._report_blocking_error)
        self._view_model.extract_failed.connect(self._report_blocking_error)

        # The history is secondary: if it cannot be written or read, the PDF is
        # already produced and a modal would be alarmist.
        self._view_model.history_failed.connect(self._report_minor_error)

    # =========================
    # Loading
    # =========================

    def open_document(self, path: Path) -> None:
        """
        Loads a PDF from outside the window: the command line, or the file
        manager's "Open with". It reuses the same path as drag & drop, including
        its validation and its error messages.
        """
        self.ui.pages.setCurrentIndex(SPLIT_PAGE)
        self.ui.btn_split.setChecked(True)
        self._on_file_chosen(Path(path))

    def _on_file_chosen(self, path: Path) -> None:
        # A new document makes the previous results stale: they described a file
        # that is no longer the one on screen.
        self._clear_results()

        self._set_status(f"Abriendo {path.name}...")
        self._view_model.load_document(path)

    def _on_document_loaded(self, document) -> None:
        details = f"{document.page_count} páginas · {document.metadata.title}"

        self.ui.drop_area.show_document(document.filename, details)
        self.ui.extract_drop_area.show_document(document.filename, details)

        self.ui.split_options.set_directory(document.storage_path.parent)
        self.ui.extract_options.set_default_parent(document.storage_path.parent)
        self._suggest_extract_destination()

        self._set_status(f"{document.filename} listo.")
        self._refresh_actions()

    # =========================
    # Splitting
    # =========================

    def _on_selection_changed(self, _text: str) -> None:
        self._refresh_actions()

        selection = self._parse_selection(self.ui.split_options.selection_text)
        if selection is not None:
            self.ui.split_options.set_suggested_destination(
                self._view_model.suggested_output_path(selection)
            )

    def _on_split_requested(self) -> None:
        selection = self._parse_selection(self.ui.split_options.selection_text)
        if selection is None:
            self._set_status("Revisá el rango de páginas.", error=True)
            return

        self.ui.split_result.clear()
        self._set_status("Procesando...")
        self._view_model.split(
            selection=selection,
            output_path=self.ui.split_options.destination,
            policy=self.ui.split_options.policy,
        )

    def _on_split_succeeded(self, response) -> None:
        self._last_split_output = response.output_path

        self._set_status(
            f"Listo: {response.output_filename} ({response.page_count} páginas)",
            success=True,
        )
        self.ui.split_result.show_result(
            title=response.output_filename,
            detail=(
                f"{formatting.format_page_count(response.page_count)} · "
                f"{formatting.format_size(response.output_size_bytes)} · "
                f"{response.output_path.parent}"
            ),
            open_text=OPEN_PDF_TEXT,
        )
        self.ui.split_options.clear()

        self._announce_finished()

    # =========================
    # Extracting
    # =========================

    def _on_extract_selection_changed(self, _text: str) -> None:
        self._refresh_actions()

    def _on_extract_mode_changed(self, _mode) -> None:
        # The suggested folder carries the mode in its name —"_figuras",
        # "_imagenes", "_paginas"— so switching mode re-suggests it. Only when
        # the user has not named one, which set_suggested_destination guarantees.
        self._suggest_extract_destination()

    def _suggest_extract_destination(self) -> None:
        """
        The folder does not depend on the page selection, so it can be offered
        the moment a document is open and stays put while ranges are edited.
        """
        self.ui.extract_options.set_suggested_destination(
            self._view_model.suggested_output_directory(self.ui.extract_options.mode)
        )

    def _on_extract_requested(self) -> None:
        options = self.ui.extract_options
        selection = self._parse_selection(options.selection_text)

        if selection is None:
            self._set_status("Revisá el rango de páginas.", error=True)
            return

        self.ui.extract_result.clear()
        self._set_status("Extrayendo...")
        self._view_model.extract_assets(
            selection=selection,
            mode=options.mode,
            output_directory=options.destination,
            dpi=options.dpi,
            policy=options.policy,
        )

    def _on_extract_succeeded(self, response) -> None:
        """
        An extraction that found nothing lands here too, not in the failure
        path: nothing broke and there is nothing to fix, so it is reported in
        the card with the mode that would work instead.
        """
        if response.found_nothing:
            self._last_extract_output = None

            self._set_status(f"Sin imágenes en {response.selection}.")
            self.ui.extract_result.show_nothing_found(
                NOTHING_FOUND_HINTS[response.mode]
            )
            self._announce_finished()
            return

        self._last_extract_output = response.output_directory
        summary = formatting.describe_export(
            _EXTRACTION_KINDS[response.mode],
            response.asset_count,
            response.total_size_bytes,
        )
        replaced = formatting.describe_replacements(response.replaced_count)
        detail = " · ".join(
            part for part in (summary, replaced, str(response.output_directory.parent)) if part
        )

        self._set_status(f"Listo: {summary}", success=True)
        self.ui.extract_result.show_result(
            title=response.output_directory.name,
            detail=detail,
            # The product is a folder, so "open" and "open folder" would be the
            # same button twice. Only one is offered.
            can_open=False,
        )

        # The destination is deliberately **not** cleared. Choosing a folder and
        # collecting several extractions in it is the point; wiping it after each
        # run sent the next one back to the suggested folder, which is exactly
        # the folder-per-run behaviour this screen was fixed to stop doing.
        self._announce_finished()

    # =========================
    # Results
    # =========================

    def _announce_finished(self) -> None:
        """
        Asks for the window's attention once an export is done.

        The card is the notice for someone watching; this is for someone who
        walked away while a 600 page book was being processed.
        """
        self._request_attention(self)

    def _clear_results(self) -> None:
        self.ui.split_result.clear()
        self.ui.extract_result.clear()
        self._last_split_output = None
        self._last_extract_output = None

    def _open_last_split(self) -> None:
        self._try_reach(self._view_model.open_export, self._last_split_output)

    def _reveal_last_split(self) -> None:
        self._try_reach(self._view_model.reveal_export, self._last_split_output)

    def _reveal_last_extraction(self) -> None:
        self._try_reach(self._view_model.reveal_export, self._last_extract_output)

    def _try_reach(self, action: Callable, path: Optional[Path]) -> None:
        """
        Runs an "open" or "reveal" and turns its failure into a message.

        The file can be gone by the time the button is pressed —moved, deleted,
        an unmounted drive— and that is the user's business, not a crash.
        """
        if path is None:
            return

        try:
            action(path)
        except Exception as error:
            self._report_blocking_error(error)

    @staticmethod
    def _parse_selection(raw: str) -> Optional[PageSelection]:
        if not raw:
            return None

        try:
            return PageSelection.parse(raw)
        except InvalidPageRangeException:
            return None

    # =========================
    # History
    # =========================

    def _show_history(self) -> None:
        self._view_model.refresh_history()
        self.ui.pages.setCurrentIndex(HISTORY_PAGE)

    def _render_history(self, entries) -> None:
        self.ui.list_history.clear()

        for entry in entries:
            item = QListWidgetItem(self._history_label(entry))
            item.setData(RECORD_ROLE, entry)
            item.setToolTip(self._history_detail(entry))

            self.ui.list_history.addItem(item)

        self._on_history_selection_changed()

    @staticmethod
    def _history_label(entry) -> str:
        """
        The list shows the produced file: that is what the user is after when
        they open the history. Source and ranges stay in the tooltip.

        An extraction also shows how many files it wrote, because its name is a
        folder and the count is the only thing that says how much is inside.
        """
        record = entry.record
        when = record.created_at.astimezone().strftime("%d/%m/%Y %H:%M")
        mark = "" if entry.is_available else "✗ "
        items = formatting.describe_items(record.kind, record.item_count)
        tail = f"   ·   {items}" if items else ""

        return f"{mark}{when}   {record.output_filename}{tail}"

    @staticmethod
    def _history_detail(entry) -> str:
        record = entry.record
        lines = [
            f"Origen: {record.source_filename}",
            f"Páginas: {record.selection}  ({record.page_count} en total)",
            f"Ubicación: {record.output_path}",
        ]

        if not entry.is_available:
            lines.append(
                "La carpeta ya no está en esta ubicación."
                if record.outputs_directory
                else "El archivo ya no está en esta ubicación."
            )

        return "\n".join(lines)

    def _on_history_selection_changed(self) -> None:
        entry = self._selected_entry()

        # Opening requires the file to exist; removing from the history does
        # not: that is precisely what one wants to do with dead entries.
        self.ui.btn_open_export.setEnabled(entry is not None and entry.is_available)
        self.ui.btn_forget_export.setEnabled(entry is not None)

    def _selected_entry(self):
        item = self.ui.list_history.currentItem()

        return item.data(RECORD_ROLE) if item is not None else None

    def _open_history_item(self, item: QListWidgetItem) -> None:
        self._open_entry(item.data(RECORD_ROLE))

    def _open_selected_export(self) -> None:
        self._open_entry(self._selected_entry())

    def _open_entry(self, entry) -> None:
        """
        Opens what the entry produced, which is not the same gesture for both
        kinds: a split PDF goes to the viewer, an extraction's folder goes to the
        file manager. Handing a directory to the viewer is how you get an error
        instead of the images.
        """
        if entry is None:
            return

        record = entry.record
        action = (
            self._view_model.reveal_export
            if record.outputs_directory
            else self._view_model.open_export
        )

        self._try_reach(action, record.output_path)

    def _forget_selected_export(self) -> None:
        """
        Takes an entry out of the history without touching what is on disk.

        It asks for no confirmation: a record is lost, not a file, and the
        selected entry is in plain sight. Reserving the dialog for what is
        irreversible keeps the user from learning to dismiss them.
        """
        entry = self._selected_entry()
        if entry is None:
            return

        self._history_repository.remove(entry.record.id)
        self._view_model.refresh_history()
        self._set_status(f"{entry.record.output_filename} salió del historial.")

    def _clear_history(self) -> None:
        if self.ui.list_history.count() == 0:
            return

        if not self._ask_confirmation(self, CLEAR_HISTORY_QUESTION, "Borrar historial"):
            return

        self._history_repository.clear()
        self._view_model.refresh_history()
        self._set_status("Historial vacío.")

    # =========================
    # Visual state
    # =========================

    def _on_busy_changed(self, busy: bool) -> None:
        self.ui.progress.setVisible(busy)
        self.ui.split_options.set_enabled(not busy)
        self.ui.extract_options.set_enabled(not busy)
        self._refresh_actions()

    def _refresh_actions(self) -> None:
        ready = self._view_model.has_document and not self._view_model.is_busy

        self.ui.btn_process.setEnabled(
            ready and self._parse_selection(self.ui.split_options.selection_text) is not None
        )
        self.ui.btn_extract_process.setEnabled(
            ready and self._parse_selection(self.ui.extract_options.selection_text) is not None
        )

    def _report_blocking_error(self, error: Exception) -> None:
        """
        Something the user explicitly asked for failed: a modal dialog, and
        the message also stays in the status bar as a reminder of what happened
        once it is closed.
        """
        self._report_minor_error(error)
        self._show_error(self, error)

    def _report_minor_error(self, error: Exception) -> None:
        self._set_status(error_messages.translate(error), error=True)

        if not error_messages.is_expected(error):
            # A bug of ours: the user sees a generic message and the detail
            # stays visible on the console so it can be reported.
            print(f"[ERROR INESPERADO] {error_messages.technical_detail(error)}")

    def _set_status(self, message: str, error: bool = False, success: bool = False) -> None:
        label = self.ui.label_status
        label.setText(message)
        label.setObjectName("ErrorText" if error else "SuccessText" if success else "")

        # Changing objectName requires recomputing the widget's style.
        label.style().unpolish(label)
        label.style().polish(label)
