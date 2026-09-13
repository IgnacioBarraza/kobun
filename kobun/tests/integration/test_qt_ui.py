"""
Tests de la interfaz sobre PDFs reales, corriendo Qt en modo offscreen.

Verifican el ciclo completo que atraviesa todas las capas: soltar un archivo,
cargarlo en el pool de hilos, dividirlo, registrar el historial y repintar la
ventana. Se omiten si falta PySide6 o PyMuPDF.
"""
import os

import pytest

pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF no instalado")
pytest.importorskip("PySide6", reason="PySide6 no instalado")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kobun.application.services.output_directory_resolver import (  # noqa: E402
    OutputDirectoryResolver,
)
from kobun.application.services.output_path_resolver import OutputPathResolver  # noqa: E402
from kobun.application.services.theme_service import ThemeService  # noqa: E402
from kobun.application.use_cases.extract_assets_use_case import (  # noqa: E402
    ExtractAssetsUseCase,
)
from kobun.application.use_cases.list_history_use_case import ListHistoryUseCase  # noqa: E402
from kobun.application.use_cases.load_pdf_use_case import LoadPdfUseCase  # noqa: E402
from kobun.application.use_cases.record_extraction_use_case import (  # noqa: E402
    RecordExtractionUseCase,
)
from kobun.application.use_cases.record_split_use_case import RecordSplitUseCase  # noqa: E402
from kobun.application.use_cases.render_page_preview_use_case import (  # noqa: E402
    RenderPagePreviewUseCase,
)
from kobun.application.use_cases.split_pdf_use_case import SplitPdfUseCase  # noqa: E402
from kobun.domain.pdf.services.asset_extractor_service import (  # noqa: E402
    AssetExtractorService,
)
from kobun.domain.pdf.services.pdf_splitter_service import PdfSplitterService  # noqa: E402
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode  # noqa: E402
from kobun.domain.pdf.value_objects.overwrite_policy import OverwritePolicy  # noqa: E402
from kobun.infrastructure.filesystem.local_file_storage import LocalFileStorage  # noqa: E402
from kobun.infrastructure.pdf_engine.pdf_document_opener import PdfDocumentOpener  # noqa: E402
from kobun.infrastructure.pdf_engine.pdf_engine_adapter import PdfEngineAdapter  # noqa: E402
from kobun.infrastructure.repositories.json_history_repository import (  # noqa: E402
    JsonHistoryRepository,
)
from kobun.infrastructure.repositories.json_preferences_repository import (  # noqa: E402
    JsonPreferencesRepository,
)
from kobun.infrastructure.repositories.pdf_asset_extractor_impl import (  # noqa: E402
    PyMuPdfAssetExtractor,
)
from kobun.infrastructure.repositories.pdf_page_renderer_impl import (  # noqa: E402
    PyMuPdfPageRenderer,
)
from kobun.infrastructure.repositories.pdf_repository_impl import PyMuPdfRepository  # noqa: E402
from kobun.infrastructure.ui.theme_loader import JsonThemeSource  # noqa: E402
from kobun.presentation import selection_feedback  # noqa: E402
from kobun.presentation.qt.windows.main_window import MainWindow  # noqa: E402
from kobun.presentation.qt.windows.ui_main_window import EXTRACT_PAGE  # noqa: E402
from kobun.presentation.viewmodels.pdf_view_model import PdfViewModel  # noqa: E402
from kobun.shared.config.theme_settings import (  # noqa: E402
    AVAILABLE_THEMES,
    DARK_THEME,
    LIGHT_THEME,
)

TIMEOUT_MS = 15000


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def source_pdf(tmp_path):
    path = tmp_path / "libro.pdf"

    doc = pymupdf.open()
    for number in range(1, 13):
        page = doc.new_page()
        page.insert_text((72, 144), f"PAGINA {number}", fontsize=40)
    doc.set_metadata({"title": "Libro Original", "author": "Ignacio"})
    doc.save(path)
    doc.close()

    return path


@pytest.fixture
def image_pdf(tmp_path):
    """
    A PDF with real embedded images, which `source_pdf` deliberately has none
    of: the text-only one is what exercises the "found nothing" path.
    """
    import struct
    import zlib

    def png(width, height, colour):
        raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))

        def chunk(tag, data):
            body = tag + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )

    path = tmp_path / "conimagenes.pdf"
    doc = pymupdf.open()

    for number in range(1, 5):
        page = doc.new_page()
        page.insert_text((72, 120), f"PAGINA {number}", fontsize=28)
        if number in (2, 3):
            page.insert_image(
                pymupdf.Rect(72, 200, 232, 320),
                stream=png(160, 120, (30, 110, 40 + number * 40)),
            )

    doc.save(path)
    doc.close()

    return path


class DialogRecorder:
    """
    Stands in for the modal dialogs: without this, a QMessageBox waiting for a
    click would leave the suite hanging until someone closed it.
    """

    def __init__(self, answer: bool = True):
        self.errors = []
        self.questions = []
        self.answer = answer

    def show_error(self, parent, error):
        self.errors.append(error)

    def ask_confirmation(self, parent, question, accept_text="Continuar"):
        self.questions.append(question)
        return self.answer


@pytest.fixture
def dialogs():
    return DialogRecorder()


def build_view_model(history_repository, file_storage=None):
    """
    The whole graph a window needs, assembled the same way KobunApplication
    does it. In one place because two tests build a window by hand, and a
    constructor that grows a dependency should not have to be chased through
    the file.
    """
    file_storage = file_storage or LocalFileStorage()
    engine = PdfEngineAdapter()
    opener = PdfDocumentOpener(engine)

    pdf_repository = PyMuPdfRepository(engine, opener)
    pdf_service = PdfSplitterService()

    return PdfViewModel(
        load_use_case=LoadPdfUseCase(pdf_repository, pdf_service),
        split_use_case=SplitPdfUseCase(
            pdf_repository, pdf_service, OutputPathResolver(file_storage)
        ),
        record_use_case=RecordSplitUseCase(history_repository),
        list_history_use_case=ListHistoryUseCase(history_repository, file_storage),
        file_storage=file_storage,
        extract_use_case=ExtractAssetsUseCase(
            pdf_repository=pdf_repository,
            asset_extractor=PyMuPdfAssetExtractor(engine, opener),
            asset_service=AssetExtractorService(),
            output_directory_resolver=OutputDirectoryResolver(file_storage),
            file_storage=file_storage,
        ),
        record_extraction_use_case=RecordExtractionUseCase(history_repository),
        preview_use_case=RenderPagePreviewUseCase(
            pdf_repository, PyMuPdfPageRenderer(engine, opener)
        ),
    )


class AttentionRecorder:
    """
    Stands in for the taskbar alert, which is invisible offscreen and therefore
    unobservable unless it is injected.
    """

    def __init__(self):
        self.calls = 0

    def __call__(self, window):
        self.calls += 1


@pytest.fixture
def attention():
    return AttentionRecorder()


@pytest.fixture
def window(qt_app, tmp_path, dialogs, attention):
    history_repository = JsonHistoryRepository(tmp_path / "datos" / "history.json")
    preferences = JsonPreferencesRepository(tmp_path / "config" / "preferences.json")

    window = MainWindow(
        build_view_model(history_repository),
        ThemeService(preferences, JsonThemeSource()),
        history_repository,
        show_error=dialogs.show_error,
        ask_confirmation=dialogs.ask_confirmation,
        request_attention=attention,
    )

    window.show()
    yield window

    window.close()


class SpawnRecorder:
    """
    Catches the file manager and viewer launches, so pressing "open folder" in a
    test does not actually spawn xdg-open on the machine running the suite.
    """

    def __init__(self):
        self.commands = []

    def __call__(self, command):
        self.commands.append(list(command))


@pytest.fixture
def spawns():
    return SpawnRecorder()


@pytest.fixture
def launcher_window(qt_app, tmp_path, dialogs, attention, spawns):
    """
    Like `window`, but with the launching side of FileStorage intercepted. Kept
    separate so the tests that never press an "open" button are not paying for
    the extra wiring.
    """
    history_repository = JsonHistoryRepository(tmp_path / "datos" / "history.json")
    preferences = JsonPreferencesRepository(tmp_path / "config" / "preferences.json")
    storage = LocalFileStorage(platform="linux", spawn=spawns)

    window = MainWindow(
        build_view_model(history_repository, file_storage=storage),
        ThemeService(preferences, JsonThemeSource()),
        history_repository,
        show_error=dialogs.show_error,
        ask_confirmation=dialogs.ask_confirmation,
        request_attention=attention,
    )
    window.show()
    yield window

    window.close()


def settle(qt_app) -> None:
    """
    Waits for the thread pool to finish and processes the pending events,
    which is how results travel from the worker to the main thread.

    Processing several times is deliberate: `processEvents` does not attend to
    what gets queued *during* its own run, and a slot can emit signals that
    trigger more work. With a single pass the tests pass offscreen but become
    timing sensitive on a real compositor.
    """
    QThreadPool.globalInstance().waitForDone(TIMEOUT_MS)

    for _ in range(3):
        qt_app.processEvents()


def load(window, qt_app, path):
    window.ui.drop_area.file_dropped.emit(path)
    settle(qt_app)


# =========================
# Carga
# =========================

def test_dropping_a_pdf_loads_it_and_shows_its_details(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    assert window.ui.drop_area.label_file.text() == "libro.pdf"
    assert "12 páginas" in window.ui.drop_area.label_details.text()


def test_split_button_stays_disabled_until_file_and_range_are_ready(window, qt_app, source_pdf):
    assert window.ui.btn_process.isEnabled() is False

    load(window, qt_app, source_pdf)
    assert window.ui.btn_process.isEnabled() is False, "Falta el rango"

    window.ui.split_options.input_selection.setText("1-3")
    assert window.ui.btn_process.isEnabled() is True


def test_an_invalid_range_keeps_the_button_disabled(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("10-2")

    assert window.ui.btn_process.isEnabled() is False


def test_a_corrupt_file_shows_a_friendly_message(window, qt_app, tmp_path):
    roto = tmp_path / "roto.pdf"
    roto.write_bytes(b"no soy un pdf")

    load(window, qt_app, roto)

    assert "no es un PDF" in window.ui.label_status.text()
    assert window.ui.btn_process.isEnabled() is False


def test_an_encrypted_file_shows_the_overridden_message(window, qt_app, tmp_path):
    protegido = tmp_path / "protegido.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(protegido, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="d", user_pw="s")
    doc.close()

    load(window, qt_app, protegido)

    assert "contraseña" in window.ui.label_status.text()


# =========================
# Splitting
# =========================

def test_the_suggested_output_appears_when_typing_a_range(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("1-3,8")

    assert window.ui.split_options.input_output.text().endswith("libro_1-3_8.pdf")


def test_a_manual_destination_is_not_overwritten_by_the_suggestion(window, qt_app, source_pdf, tmp_path):
    load(window, qt_app, source_pdf)
    window.ui.split_options.set_destination(tmp_path / "mio.pdf")

    window.ui.split_options.input_selection.setText("1-3")

    assert window.ui.split_options.input_output.text() == "mio.pdf"


def test_the_destination_field_shows_only_the_filename(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("1-3,8")

    assert window.ui.split_options.input_output.text() == "libro_1-3_8.pdf"
    assert "/" not in window.ui.split_options.input_output.text()


def test_the_folder_is_shown_separately(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    assert window.ui.split_options.label_folder.toolTip() == str(source_pdf.parent)
    assert "Carpeta:" in window.ui.split_options.label_folder.text()


def test_a_typed_name_lands_in_the_document_folder(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.split_options.input_output.setText("capitulo uno.pdf")

    assert window.ui.split_options.destination == source_pdf.parent / "capitulo uno.pdf"


def test_a_typed_name_without_extension_still_works(window, qt_app, source_pdf):
    """The field asks for a name, not a path: demanding ".pdf" would be an avoidable error."""
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.split_options.input_output.setText("capitulo uno")

    window.ui.btn_process.click()
    settle(qt_app)

    assert (source_pdf.parent / "capitulo uno.pdf").exists()


def test_splitting_writes_the_file_and_reports_success(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3,8")

    window.ui.btn_process.click()
    settle(qt_app)

    generado = source_pdf.parent / "libro_1-3_8.pdf"
    assert generado.exists()
    assert "Listo" in window.ui.label_status.text()

    doc = pymupdf.open(generado)
    try:
        assert doc.page_count == 4
    finally:
        doc.close()


def test_the_ui_is_not_blocked_while_working(window, qt_app, source_pdf):
    """
    The work goes to the pool: by the time the split fires the window is
    already marked busy, with the spinner visible and the options disabled,
    instead of having frozen until it finished.
    """
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")

    window.ui.btn_process.click()
    ocupada_durante = window.ui.progress.isVisible()
    opciones_bloqueadas = not window.ui.split_options.input_selection.isEnabled()
    settle(qt_app)

    assert ocupada_durante is True
    assert opciones_bloqueadas is True
    assert window.ui.progress.isVisible() is False, "El spinner se oculta al terminar"
    assert window.ui.split_options.input_selection.isEnabled() is True


def test_an_existing_destination_is_reported_instead_of_overwritten(window, qt_app, source_pdf, tmp_path):
    taken = tmp_path / "ocupado.pdf"
    taken.write_bytes(b"contenido previo")

    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.split_options.input_output.setText(str(taken))

    window.ui.btn_process.click()
    settle(qt_app)

    assert "ya existe" in window.ui.label_status.text()
    assert taken.read_bytes() == b"contenido previo"


def test_the_rename_policy_can_be_chosen_from_the_ui(window, qt_app, source_pdf, tmp_path):
    taken = tmp_path / "ocupado.pdf"
    taken.write_bytes(b"contenido previo")

    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.split_options.set_destination(taken)
    window.ui.split_options.set_policy(OverwritePolicy.RENAME)

    window.ui.btn_process.click()
    settle(qt_app)

    assert (tmp_path / "ocupado_1.pdf").exists()
    assert taken.read_bytes() == b"contenido previo"


# =========================
# Historial
# =========================

def test_a_successful_split_appears_in_the_history(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("2-4")
    window.ui.btn_process.click()
    settle(qt_app)

    assert window.ui.list_history.count() == 1
    assert window.ui.list_history.item(0).text().endswith("libro_2-4.pdf")


def test_the_history_row_shows_only_the_generated_file(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("2-4")
    window.ui.btn_process.click()
    settle(qt_app)

    text = window.ui.list_history.item(0).text()

    assert "libro_2-4.pdf" in text
    assert "->" not in text, "El origen y la flecha ensuciaban la fila"
    assert "[2-4]" not in text


def test_the_history_tooltip_keeps_the_full_detail(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("2-4")
    window.ui.btn_process.click()
    settle(qt_app)

    tooltip = window.ui.list_history.item(0).toolTip()

    assert "libro.pdf" in tooltip
    assert "2-4" in tooltip
    assert "3 en total" in tooltip


def test_deleted_exports_are_flagged_in_the_list(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("2-4")
    window.ui.btn_process.click()
    settle(qt_app)

    (source_pdf.parent / "libro_2-4.pdf").unlink()
    window.ui.btn_history.click()
    settle(qt_app)

    item = window.ui.list_history.item(0)
    assert item.text().startswith("✗")
    assert window.ui.btn_open_export.isEnabled() is False


def test_clearing_the_history_empties_the_list(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("2-4")
    window.ui.btn_process.click()
    settle(qt_app)

    window.ui.btn_clear_history.click()

    assert window.ui.list_history.count() == 0


# =========================
# Temas
# =========================

def test_the_window_starts_with_a_stylesheet(window):
    assert len(window.styleSheet()) > 0


def test_the_selector_lists_every_shipped_theme(window):
    combo = window.ui.combo_theme
    nombres = [combo.itemData(i) for i in range(combo.count()) if combo.itemData(i)]

    assert nombres == list(AVAILABLE_THEMES)


def test_the_selector_separates_light_from_dark(window):
    """With nine palettes, one unbroken list is hard to read."""
    combo = window.ui.combo_theme
    rows = [combo.itemData(i) for i in range(combo.count())]

    assert combo.count() == len(AVAILABLE_THEMES) + 1, "the separator is missing"
    assert rows.count(None) == 1

    cut = rows.index(None)
    before = [n for n in rows[:cut]]
    after = [n for n in rows[cut + 1:]]

    assert all(not JsonThemeSource().load(n).is_dark for n in before)
    assert all(JsonThemeSource().load(n).is_dark for n in after)


def test_the_separator_cannot_be_chosen_as_a_theme(window):
    """Un separador no tiene nombre de tema; elegirlo no debe romper nada."""
    combo = window.ui.combo_theme
    separator_index = [combo.itemData(i) for i in range(combo.count())].index(None)
    before = window.styleSheet()

    window._on_theme_chosen(separator_index)

    assert window.styleSheet() == before


def test_the_selector_shows_readable_labels(window):
    etiquetas = [window.ui.combo_theme.itemText(i) for i in range(window.ui.combo_theme.count())]

    assert "Claro" in etiquetas
    assert "Sumi · tinta" in etiquetas
    assert "Yozora · noche" in etiquetas
    assert "washi_shu" not in etiquetas


def test_the_theme_labels_fit_the_sidebar(window):
    """
    El sidebar es angosto; una etiqueta larga se recorta con puntos y queda
    sucia. Se acota el largo en vez de descubrirlo mirando capturas.
    """
    combo = window.ui.combo_theme
    etiquetas = [combo.itemText(i) for i in range(combo.count()) if combo.itemData(i)]

    for etiqueta in etiquetas:
        assert len(etiqueta) <= 20, f"'{etiqueta}' no entra en el selector"


def test_the_selector_starts_on_the_active_theme(window):
    assert window.ui.combo_theme.currentData() == LIGHT_THEME


def test_choosing_a_theme_repaints_the_window(window):
    combo = window.ui.combo_theme
    before = window.styleSheet()

    combo.setCurrentIndex(combo.findData("sumi"))

    assert window.styleSheet() != before


@pytest.mark.parametrize("name", AVAILABLE_THEMES)
def test_every_theme_produces_a_stylesheet(window, name):
    combo = window.ui.combo_theme

    combo.setCurrentIndex(combo.findData(name))

    assert len(window.styleSheet()) > 0


def test_building_the_selector_does_not_save_a_preference(qt_app, tmp_path, dialogs):
    """
    While building the combo, setCurrentIndex would emit the change and save a
    preference the user never chose.
    """
    from kobun.presentation.qt.windows.main_window import MainWindow as Window

    prefs_path = tmp_path / "prefs.json"
    history_repository = JsonHistoryRepository(tmp_path / "datos" / "history.json")

    view_model = build_view_model(history_repository)
    window = Window(
        view_model,
        ThemeService(JsonPreferencesRepository(prefs_path), JsonThemeSource()),
        history_repository,
        show_error=dialogs.show_error,
        ask_confirmation=dialogs.ask_confirmation,
    )

    try:
        assert not prefs_path.exists(), "Abrir la ventana no debe escribir preferencias"
    finally:
        window.close()


def test_the_chosen_theme_survives_a_new_window(qt_app, tmp_path):
    preferences = JsonPreferencesRepository(tmp_path / "preferences.json")
    service = ThemeService(preferences, JsonThemeSource())

    assert service.current().name == LIGHT_THEME
    service.select("matcha")

    otra_sesion = ThemeService(
        JsonPreferencesRepository(preferences.file_path), JsonThemeSource()
    )
    assert otra_sesion.current().name == "matcha"


# =========================
# Icono
# =========================

def test_the_window_has_an_icon(window):
    icon = window.windowIcon()

    assert not icon.isNull(), "the window would be left with Qt's generic icon"


def test_the_icon_carries_every_declared_size(window):
    from kobun.shared.config.app_settings import APP_ICON_SIZES

    available = {size.width() for size in window.windowIcon().availableSizes()}

    assert available == set(APP_ICON_SIZES)


def test_the_icon_renders_at_small_sizes_without_being_empty(window):
    """
    Qt returns an empty pixmap if the file exists but could not be decoded.
    """
    for side in (16, 32, 48):
        pixmap = window.windowIcon().pixmap(side, side)

        assert not pixmap.isNull()
        assert pixmap.width() == side


def test_the_icon_keeps_its_transparent_corners(window):
    """
    Regression of the black frame: the pixmap's corner has to be transparent,
    not black.
    """
    image = window.windowIcon().pixmap(64, 64).toImage()

    assert image.pixelColor(0, 0).alpha() == 0, "the corner is not transparent"
    assert image.pixelColor(32, 32).alpha() == 255, "the centre should be opaque"


# =========================
# Opening from outside the window
# =========================

def test_open_document_loads_a_pdf_from_outside(window, qt_app, source_pdf):
    """
    This is the path taken by the file manager's "Open with" and the command
    line.
    """
    window.open_document(source_pdf)
    settle(qt_app)

    assert window.ui.drop_area.label_file.text() == "libro.pdf"
    assert window.ui.split_options.label_folder.toolTip() == str(source_pdf.parent)


def test_open_document_switches_to_the_split_page(window, qt_app, source_pdf):
    """If the app starts on the history page, the opened file would not show."""
    window.ui.btn_history.click()
    settle(qt_app)

    window.open_document(source_pdf)
    settle(qt_app)

    assert window.ui.pages.currentIndex() == 0
    assert window.ui.btn_split.isChecked()


def test_open_document_reports_a_bad_file_like_the_drop_area(window, qt_app, dialogs, tmp_path):
    roto = tmp_path / "roto.pdf"
    roto.write_bytes(b"no soy un pdf")

    window.open_document(roto)
    settle(qt_app)

    assert len(dialogs.errors) == 1
    assert "no es un PDF" in window.ui.label_status.text()


# =========================
# Quitar una entrada del historial
# =========================

def export(window, qt_app, source_pdf, seleccion="2-4"):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText(seleccion)
    window.ui.btn_process.click()
    settle(qt_app)


def test_forget_removes_only_the_selected_entry(window, qt_app, source_pdf):
    export(window, qt_app, source_pdf, "2-4")
    export(window, qt_app, source_pdf, "8-9")
    window.ui.btn_history.click()
    settle(qt_app)
    assert window.ui.list_history.count() == 2

    window.ui.list_history.setCurrentRow(0)
    quitado = window.ui.list_history.item(0).text()
    window.ui.btn_forget_export.click()
    settle(qt_app)

    assert window.ui.list_history.count() == 1
    assert window.ui.list_history.item(0).text() != quitado


def test_forget_does_not_delete_the_pdf(window, qt_app, source_pdf):
    """Se pierde el registro, no el archivo."""
    export(window, qt_app, source_pdf, "2-4")
    generado = source_pdf.parent / "libro_2-4.pdf"

    window.ui.btn_history.click()
    settle(qt_app)
    window.ui.list_history.setCurrentRow(0)
    window.ui.btn_forget_export.click()
    settle(qt_app)

    assert generado.exists()
    assert window.ui.list_history.count() == 0


def test_forget_asks_no_confirmation(window, qt_app, dialogs, source_pdf):
    """Only the irreversible asks; if everything asks, nobody reads."""
    export(window, qt_app, source_pdf, "2-4")
    window.ui.btn_history.click()
    settle(qt_app)
    window.ui.list_history.setCurrentRow(0)

    window.ui.btn_forget_export.click()

    assert dialogs.questions == []


def test_forget_is_available_for_dead_entries_but_open_is_not(window, qt_app, source_pdf):
    """
    This is precisely the case that motivated the button: a file that is gone
    and that previously could only be removed by clearing the whole history.
    """
    export(window, qt_app, source_pdf, "2-4")
    (source_pdf.parent / "libro_2-4.pdf").unlink()

    window.ui.btn_history.click()
    settle(qt_app)
    window.ui.list_history.setCurrentRow(0)

    assert window.ui.btn_open_export.isEnabled() is False
    assert window.ui.btn_forget_export.isEnabled() is True

    window.ui.btn_forget_export.click()
    settle(qt_app)

    assert window.ui.list_history.count() == 0


def test_forget_is_disabled_without_a_selection(window, qt_app, source_pdf):
    export(window, qt_app, source_pdf, "2-4")
    window.ui.btn_history.click()
    settle(qt_app)
    window.ui.list_history.setCurrentRow(-1)

    assert window.ui.btn_forget_export.isEnabled() is False


def test_forgetting_survives_a_reload(window, qt_app, source_pdf):
    """The removal is persisted, not just taken off the list on screen."""
    export(window, qt_app, source_pdf, "2-4")
    window.ui.btn_history.click()
    settle(qt_app)
    window.ui.list_history.setCurrentRow(0)
    window.ui.btn_forget_export.click()
    settle(qt_app)

    window._view_model.refresh_history()
    settle(qt_app)

    assert window.ui.list_history.count() == 0


# =========================
# Visible version
# =========================

def test_the_window_shows_the_package_version(window):
    """
    With the version in plain sight, the downloaded file can simply be called
    "kobun" without losing the ability to tell which version is running.
    """
    import kobun

    assert window.ui.label_version.text() == f"v{kobun.__version__}"


def test_the_version_label_is_not_empty(window):
    assert window.ui.label_version.text().strip() not in ("", "v")
# =========================
# Tarjeta de resultado
# =========================

def test_no_result_card_is_shown_before_exporting(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    assert window.ui.split_result.isVisible() is False
    assert window.ui.extract_result.isVisible() is False


def test_a_split_shows_what_it_produced_and_how_to_reach_it(window, qt_app, source_pdf):
    """
    The gap the feedback pointed at: the status line said it worked, but the only
    way to reach the file was switching to the history tab.
    """
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.btn_process.click()
    settle(qt_app)

    card = window.ui.split_result

    assert card.isVisible() is True
    assert "libro_1-3.pdf" in card.label_title.text()
    assert card.btn_open.isVisibleTo(card) is True
    assert card.btn_reveal.isVisibleTo(card) is True


def test_the_card_reports_pages_and_size(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.btn_process.click()
    settle(qt_app)

    detail = window.ui.split_result.label_detail.toolTip()

    assert "3 páginas" in detail
    assert "KB" in detail or "B" in detail


def test_the_card_disappears_when_a_new_document_is_loaded(window, qt_app, source_pdf, tmp_path):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.btn_process.click()
    settle(qt_app)
    assert window.ui.split_result.isVisible() is True

    otro = tmp_path / "otro.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(otro)
    doc.close()
    load(window, qt_app, otro)

    assert window.ui.split_result.isVisible() is False, "Describía un archivo que ya no está en pantalla"


def test_the_card_disappears_while_the_next_export_runs(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.btn_process.click()
    settle(qt_app)

    window.ui.split_options.input_selection.setText("5-7")
    window.ui.btn_process.click()
    durante = window.ui.split_result.isVisible()
    settle(qt_app)

    assert durante is False
    assert "libro_5-7.pdf" in window.ui.split_result.label_title.text()


def test_the_open_button_launches_the_generated_pdf(launcher_window, qt_app, source_pdf, spawns):
    load(launcher_window, qt_app, source_pdf)
    launcher_window.ui.split_options.input_selection.setText("1-3")
    launcher_window.ui.btn_process.click()
    settle(qt_app)

    launcher_window.ui.split_result.btn_open.click()

    assert spawns.commands == [["xdg-open", str(source_pdf.parent / "libro_1-3.pdf")]]


def test_the_folder_button_shows_the_pdf_in_its_folder(launcher_window, qt_app, source_pdf, spawns):
    load(launcher_window, qt_app, source_pdf)
    launcher_window.ui.split_options.input_selection.setText("1-3")
    launcher_window.ui.btn_process.click()
    settle(qt_app)

    launcher_window.ui.split_result.btn_reveal.click()

    assert spawns.commands == [["xdg-open", str(source_pdf.parent)]]


def test_a_deleted_export_reports_instead_of_crashing(launcher_window, qt_app, source_pdf, dialogs):
    """The file can be gone by the time the button is pressed."""
    load(launcher_window, qt_app, source_pdf)
    launcher_window.ui.split_options.input_selection.setText("1-3")
    launcher_window.ui.btn_process.click()
    settle(qt_app)

    (source_pdf.parent / "libro_1-3.pdf").unlink()
    launcher_window.ui.split_result.btn_open.click()

    assert len(dialogs.errors) == 1
    assert "ya no está disponible" in launcher_window.ui.label_status.text()


# =========================
# Aviso de que terminó
# =========================

def test_a_finished_split_asks_for_the_window_s_attention(window, qt_app, source_pdf, attention):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.btn_process.click()
    settle(qt_app)

    assert attention.calls == 1


def test_loading_a_document_does_not_ask_for_attention(window, qt_app, source_pdf, attention):
    """Only a finished export does; the user is right there when they drop a file."""
    load(window, qt_app, source_pdf)

    assert attention.calls == 0


def test_a_failed_split_does_not_ask_for_attention(window, qt_app, source_pdf, tmp_path, attention):
    taken = tmp_path / "ocupado.pdf"
    taken.write_bytes(b"contenido previo")

    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.split_options.input_output.setText(str(taken))
    window.ui.btn_process.click()
    settle(qt_app)

    assert attention.calls == 0, "El error ya interrumpe con un diálogo"


def test_no_modal_dialog_is_opened_on_success(window, qt_app, source_pdf, dialogs):
    """
    A dialog per export is a dialog people learn to dismiss without reading, and
    the project reserves those for what cannot be undone.
    """
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.btn_process.click()
    settle(qt_app)

    assert dialogs.errors == []
    assert dialogs.questions == []


# =========================
# Nombre sugerido
# =========================

def test_the_suggested_name_follows_the_range_as_it_is_corrected(window, qt_app, source_pdf):
    """
    Typing "1-3" and correcting it to "1-4" has to rename the output; leaving the
    first suggestion there produced a file named after pages it did not contain.
    """
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("1-3")
    assert window.ui.split_options.input_output.text() == "libro_1-3.pdf"

    window.ui.split_options.input_selection.setText("1-4")
    assert window.ui.split_options.input_output.text() == "libro_1-4.pdf"


def test_a_name_typed_by_hand_still_survives_a_range_change(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.split_options.input_output.setText("capitulo uno.pdf")

    window.ui.split_options.input_selection.setText("5-9")

    assert window.ui.split_options.input_output.text() == "capitulo uno.pdf"


# =========================
# Extracción: la pantalla
# =========================

def test_the_extract_nav_shows_the_extraction_page(window):
    window.ui.btn_extract.click()

    assert window.ui.pages.currentIndex() == EXTRACT_PAGE


def test_a_document_loaded_on_one_page_is_available_on_the_other(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    assert window.ui.extract_drop_area.label_file.text() == "libro.pdf"
    assert "12 páginas" in window.ui.extract_drop_area.label_details.text()


def test_a_document_dropped_on_the_extract_page_reaches_the_split_page(window, qt_app, source_pdf):
    window.ui.extract_drop_area.file_dropped.emit(source_pdf)
    settle(qt_app)

    assert window.ui.drop_area.label_file.text() == "libro.pdf"
    assert window.ui.split_options.input_selection.isEnabled() is True


def test_the_extract_button_stays_disabled_until_file_and_range_are_ready(window, qt_app, source_pdf):
    assert window.ui.btn_extract_process.isEnabled() is False

    load(window, qt_app, source_pdf)
    assert window.ui.btn_extract_process.isEnabled() is False, "Falta el rango"

    window.ui.extract_options.input_selection.setText("1-3")
    assert window.ui.btn_extract_process.isEnabled() is True


def test_an_invalid_range_keeps_the_extract_button_disabled(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    window.ui.extract_options.input_selection.setText("10-2")

    assert window.ui.btn_extract_process.isEnabled() is False


def test_the_resolution_only_shows_in_the_mode_that_uses_it(window):
    options = window.ui.extract_options
    window.ui.btn_extract.click()

    options.set_mode(ExtractionMode.EMBEDDED_IMAGES)
    assert options.row_dpi.isVisibleTo(options) is False, "Una imagen guardada sale como está"

    options.set_mode(ExtractionMode.PAGE_RASTER)
    assert options.row_dpi.isVisibleTo(options) is True


def test_the_suggested_folder_appears_as_soon_as_the_pdf_is_open(window, qt_app, source_pdf):
    """No range needed: the folder does not depend on the selection any more."""
    load(window, qt_app, source_pdf)

    assert window.ui.extract_options.output_name == "libro_figuras"


def test_the_suggested_folder_does_not_change_with_the_range(window, qt_app, source_pdf):
    """
    So extracting 1-5 and then 6-10 lands in one folder. It used to carry the
    selection, which produced a folder per run.
    """
    load(window, qt_app, source_pdf)

    window.ui.extract_options.input_selection.setText("1-5")
    first = window.ui.extract_options.output_name
    window.ui.extract_options.input_selection.setText("6-10")

    assert window.ui.extract_options.output_name == first == "libro_figuras"


def test_the_suggested_folder_follows_the_mode(window, qt_app, source_pdf):
    """The mode is part of the folder's name, so switching has to re-suggest it."""
    load(window, qt_app, source_pdf)

    window.ui.extract_options.set_mode(ExtractionMode.PAGE_RASTER)
    assert window.ui.extract_options.output_name == "libro_paginas"

    window.ui.extract_options.set_mode(ExtractionMode.EMBEDDED_IMAGES)
    assert window.ui.extract_options.output_name == "libro_imagenes"


def test_a_folder_typed_by_hand_is_not_overwritten_by_the_suggestion(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.extract_options.input_selection.setText("1-3")
    window.ui.extract_options.input_output.setText("mis figuras")

    window.ui.extract_options.set_mode(ExtractionMode.PAGE_RASTER)
    window.ui.extract_options.input_selection.setText("5-9")

    assert window.ui.extract_options.output_name == "mis figuras"


# =========================
# Extracción: el resultado
# =========================

def test_extracting_images_writes_them_and_reports_success(window, qt_app, image_pdf):
    load(window, qt_app, image_pdf)
    window.ui.extract_options.input_selection.setText("1-4")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    folder = image_pdf.parent / "conimagenes_figuras"

    assert folder.is_dir()
    assert list(folder.iterdir()), "La carpeta no puede quedar vacía"
    assert "Listo" in window.ui.label_status.text()


def test_the_extraction_card_reports_the_folder_and_the_count(window, qt_app, image_pdf):
    window.ui.btn_extract.click()
    load(window, qt_app, image_pdf)
    window.ui.extract_options.input_selection.setText("1-4")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    card = window.ui.extract_result

    assert card.isVisible() is True
    assert "conimagenes_figuras" in card.label_title.text()
    assert "2 imágenes" in card.label_detail.toolTip()


def test_the_extraction_card_offers_only_the_folder(window, qt_app, image_pdf):
    """Its product is a folder, so "open" and "open folder" would be one button twice."""
    load(window, qt_app, image_pdf)
    window.ui.extract_options.input_selection.setText("1-4")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    card = window.ui.extract_result

    assert card.btn_open.isVisibleTo(card) is False
    assert card.btn_reveal.isVisibleTo(card) is True


def test_the_extraction_folder_button_opens_the_folder(launcher_window, qt_app, image_pdf, spawns):
    load(launcher_window, qt_app, image_pdf)
    launcher_window.ui.extract_options.input_selection.setText("1-4")
    launcher_window.ui.btn_extract_process.click()
    settle(qt_app)

    launcher_window.ui.extract_result.btn_reveal.click()

    folder = image_pdf.parent / "conimagenes_figuras"
    assert spawns.commands == [["xdg-open", str(folder)]]


def test_rendering_pages_writes_one_png_each(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.extract_options.set_mode(ExtractionMode.PAGE_RASTER)
    window.ui.extract_options.input_selection.setText("2-4")
    window.ui.extract_options.spin_dpi.setValue(72)
    window.ui.btn_extract_process.click()
    settle(qt_app)

    folder = source_pdf.parent / "libro_paginas"

    assert sorted(p.name for p in folder.iterdir()) == [
        "libro_p002.png",
        "libro_p003.png",
        "libro_p004.png",
    ]


def test_finding_nothing_is_reported_without_a_dialog(window, qt_app, source_pdf, dialogs):
    """
    Nothing failed and there is nothing to fix, so it is not an error: the card
    says so and names the mode that would work.
    """
    window.ui.btn_extract.click()
    load(window, qt_app, source_pdf)
    window.ui.extract_options.input_selection.setText("1-12")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    card = window.ui.extract_result

    assert dialogs.errors == []
    assert card.isVisible() is True
    assert "nada para extraer" in card.label_title.text()
    assert "PNG" in card.label_detail.text(), "Tiene que nombrar el modo que sí funciona"


def test_finding_nothing_offers_no_buttons(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.extract_options.input_selection.setText("1-12")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    card = window.ui.extract_result

    assert card.btn_open.isVisibleTo(card) is False
    assert card.btn_reveal.isVisibleTo(card) is False, "No quedó ninguna carpeta que abrir"


def test_finding_nothing_leaves_no_folder_next_to_the_pdf(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.extract_options.input_selection.setText("1-12")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    assert sorted(p.name for p in source_pdf.parent.iterdir()) == ["libro.pdf"]


def test_finding_nothing_is_not_recorded_in_the_history(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.extract_options.input_selection.setText("1-12")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    assert window.ui.list_history.count() == 0


def test_a_finished_extraction_asks_for_the_window_s_attention(window, qt_app, image_pdf, attention):
    load(window, qt_app, image_pdf)
    window.ui.extract_options.input_selection.setText("1-4")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    assert attention.calls == 1


def test_an_extraction_that_found_nothing_still_asks_for_attention(window, qt_app, source_pdf, attention):
    """
    The operation finished, which is what the notice is about. Someone who walked
    away wants to know it is done, whatever the outcome was.
    """
    load(window, qt_app, source_pdf)
    window.ui.extract_options.input_selection.setText("1-12")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    assert attention.calls == 1


def test_a_chosen_folder_collects_two_extractions(window, qt_app, image_pdf, tmp_path):
    """
    What the folder-per-run design got wrong, from the screen: pick a folder,
    extract twice, find everything in it.
    """
    target = tmp_path / "mis figuras"

    load(window, qt_app, image_pdf)
    window.ui.extract_options.set_destination(target)

    window.ui.extract_options.input_selection.setText("2")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    window.ui.extract_options.input_selection.setText("3")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    names = sorted(p.name for p in target.iterdir())
    assert any("_p002_" in name for name in names)
    assert any("_p003_" in name for name in names)


def test_someone_else_s_files_in_the_chosen_folder_are_left_alone(window, qt_app, image_pdf, tmp_path):
    target = tmp_path / "mis figuras"
    target.mkdir()
    (target / "ajeno.txt").write_bytes(b"no me toques")

    load(window, qt_app, image_pdf)
    window.ui.extract_options.set_destination(target)
    window.ui.extract_options.input_selection.setText("1-4")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    assert (target / "ajeno.txt").read_bytes() == b"no me toques"
    assert "Listo" in window.ui.label_status.text()


def test_re_extracting_replaces_and_says_so(window, qt_app, image_pdf, tmp_path):
    target = tmp_path / "salida"

    load(window, qt_app, image_pdf)
    window.ui.extract_options.set_destination(target)
    window.ui.extract_options.input_selection.setText("1-4")

    window.ui.btn_extract_process.click()
    settle(qt_app)
    first = sorted(p.name for p in target.iterdir())

    window.ui.btn_extract_process.click()
    settle(qt_app)

    assert sorted(p.name for p in target.iterdir()) == first, "No debe duplicar"
    assert "reemplazado" in window.ui.extract_result.label_detail.toolTip()


def test_the_ui_is_not_blocked_while_extracting(window, qt_app, image_pdf):
    load(window, qt_app, image_pdf)
    window.ui.extract_options.input_selection.setText("1-4")

    window.ui.btn_extract_process.click()
    ocupada = window.ui.progress.isVisible()
    bloqueada = not window.ui.extract_options.input_selection.isEnabled()
    settle(qt_app)

    assert ocupada is True
    assert bloqueada is True
    assert window.ui.progress.isVisible() is False
    assert window.ui.extract_options.input_selection.isEnabled() is True


# =========================
# Extracción: el historial
# =========================

def test_an_extraction_appears_in_the_history_with_its_count(window, qt_app, image_pdf):
    load(window, qt_app, image_pdf)
    window.ui.extract_options.input_selection.setText("1-4")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    row = window.ui.list_history.item(0).text()

    assert "conimagenes_figuras" in row
    assert "2 imágenes" in row, "El nombre es una carpeta; la cuenta es lo único que dice cuánto hay"


def test_opening_an_extraction_from_the_history_shows_its_folder(launcher_window, qt_app, image_pdf, spawns):
    """
    Handing a directory to the PDF viewer is how you get an error instead of the
    images, so the gesture differs by kind.
    """
    load(launcher_window, qt_app, image_pdf)
    launcher_window.ui.extract_options.input_selection.setText("1-4")
    launcher_window.ui.btn_extract_process.click()
    settle(qt_app)

    launcher_window.ui.btn_history.click()
    settle(qt_app)
    launcher_window.ui.list_history.setCurrentRow(0)
    launcher_window.ui.btn_open_export.click()

    folder = image_pdf.parent / "conimagenes_figuras"
    assert spawns.commands == [["xdg-open", str(folder)]]


def test_opening_a_split_from_the_history_still_launches_the_viewer(launcher_window, qt_app, source_pdf, spawns):
    load(launcher_window, qt_app, source_pdf)
    launcher_window.ui.split_options.input_selection.setText("2-4")
    launcher_window.ui.btn_process.click()
    settle(qt_app)

    launcher_window.ui.btn_history.click()
    settle(qt_app)
    launcher_window.ui.list_history.setCurrentRow(0)
    launcher_window.ui.btn_open_export.click()

    assert spawns.commands == [["xdg-open", str(source_pdf.parent / "libro_2-4.pdf")]]


def test_a_deleted_extraction_folder_is_flagged_in_the_list(window, qt_app, image_pdf):
    import shutil

    load(window, qt_app, image_pdf)
    window.ui.extract_options.input_selection.setText("1-4")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    shutil.rmtree(image_pdf.parent / "conimagenes_figuras")
    window.ui.btn_history.click()
    settle(qt_app)

    assert window.ui.list_history.item(0).text().startswith("✗")


def test_splits_and_extractions_share_one_history(window, qt_app, image_pdf):
    load(window, qt_app, image_pdf)

    window.ui.split_options.input_selection.setText("1-2")
    window.ui.btn_process.click()
    settle(qt_app)

    window.ui.extract_options.input_selection.setText("1-4")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    assert window.ui.list_history.count() == 2
# =========================
# La carpeta elegida no se mueve
# =========================

def test_a_chosen_folder_survives_loading_another_pdf(window, qt_app, image_pdf, tmp_path):
    """
    Regression. The widget used to hold the destination as a parent plus a name,
    so loading another document replaced the parent while the name stayed on
    screen: the field went on saying "mis imagenes" while the files landed in
    `<new pdf folder>/mis imagenes`.
    """
    target = tmp_path / "mis imagenes"
    otro = tmp_path / "otro.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(otro)
    doc.close()

    load(window, qt_app, image_pdf)
    window.ui.extract_options.set_destination(target)

    load(window, qt_app, otro)

    assert window.ui.extract_options.destination == target


def test_both_documents_extract_into_the_chosen_folder(window, qt_app, image_pdf, tmp_path):
    # In a directory of its own: the fixtures share tmp_path, so a folder named
    # directly under it would be the source's neighbour and prove nothing.
    target = tmp_path / "salida" / "mis imagenes"
    otro = tmp_path / "otro.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(80, 200, 300, 350), fill=(0.2, 0.4, 0.8), color=(0, 0, 0))
    doc.save(otro)
    doc.close()

    load(window, qt_app, image_pdf)
    window.ui.extract_options.set_destination(target)
    window.ui.extract_options.input_selection.setText("2")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    load(window, qt_app, otro)
    window.ui.extract_options.input_selection.setText("1")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    names = sorted(p.name for p in target.iterdir())
    assert any(name.startswith("conimagenes_") for name in names)
    assert any(name.startswith("otro_") for name in names)
    assert not (image_pdf.parent / "mis imagenes").exists(), "No debe crear una carpeta paralela"


def test_a_chosen_folder_survives_a_mode_change(window, qt_app, image_pdf, tmp_path):
    target = tmp_path / "mis imagenes"

    load(window, qt_app, image_pdf)
    window.ui.extract_options.set_destination(target)
    window.ui.extract_options.set_mode(ExtractionMode.PAGE_RASTER)

    assert window.ui.extract_options.destination == target


def test_a_chosen_folder_survives_extracting(window, qt_app, image_pdf, tmp_path):
    target = tmp_path / "mis imagenes"

    load(window, qt_app, image_pdf)
    window.ui.extract_options.set_destination(target)
    window.ui.extract_options.input_selection.setText("2")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    assert window.ui.extract_options.destination == target


def test_an_absolute_path_typed_by_hand_is_used_as_it_stands(window, qt_app, image_pdf, tmp_path):
    load(window, qt_app, image_pdf)

    window.ui.extract_options.input_output.setText(str(tmp_path / "a mano"))

    assert window.ui.extract_options.destination == tmp_path / "a mano"


def test_a_bare_name_lands_next_to_the_pdf(window, qt_app, image_pdf):
    """
    Which is why the suggestion can stay short: "conimagenes_figuras" reads
    better in the field than the whole path.
    """
    load(window, qt_app, image_pdf)

    window.ui.extract_options.input_output.setText("figuras sueltas")

    assert window.ui.extract_options.destination == image_pdf.parent / "figuras sueltas"


def test_the_screen_reports_where_the_files_will_go(window, qt_app, image_pdf):
    """
    With a bare name in the field, the only way to know where it lands is to see
    it spelled out.
    """
    load(window, qt_app, image_pdf)

    assert window.ui.extract_options.label_folder.toolTip() == str(
        image_pdf.parent / "conimagenes_figuras"
    )
    assert "Se guardan en:" in window.ui.extract_options.label_folder.text()


def test_an_empty_destination_falls_back_to_the_suggestion(window, qt_app, image_pdf):
    load(window, qt_app, image_pdf)
    window.ui.extract_options.input_output.clear()

    assert window.ui.extract_options.destination is None, "El use case usa su sugerencia"

    window.ui.extract_options.input_selection.setText("2")
    window.ui.btn_extract_process.click()
    settle(qt_app)

    assert (image_pdf.parent / "conimagenes_figuras").is_dir()


def test_the_resolved_location_is_not_repeated_under_a_full_path(window, qt_app, image_pdf, tmp_path):
    """
    Right after picking a folder the field already spells the whole path out, so
    saying it again underneath is noise.
    """
    load(window, qt_app, image_pdf)
    options = window.ui.extract_options

    window.ui.btn_extract.click()
    options.set_destination(tmp_path / "salida" / "mis figuras")

    assert options.label_folder.isVisibleTo(options) is False

    options.input_output.setText("un nombre suelto")
    assert options.label_folder.isVisibleTo(options) is True

# =========================
# Lo mismo en Dividir
# =========================

def test_a_chosen_split_folder_survives_loading_another_pdf(window, qt_app, source_pdf, tmp_path):
    """
    Regression, same class as the extraction one: choosing recortes/ and then
    opening another PDF wrote next to that PDF instead, with the chosen filename
    still on screen.
    """
    chosen = tmp_path / "recortes"
    chosen.mkdir()
    otro = tmp_path / "otro.pdf"
    doc = pymupdf.open()
    for _ in range(4):
        doc.new_page()
    doc.save(otro)
    doc.close()

    load(window, qt_app, source_pdf)
    window.ui.split_options.set_destination(chosen / "capitulo uno.pdf")

    load(window, qt_app, otro)
    window.ui.split_options.input_selection.setText("2-3")

    assert window.ui.split_options.destination.parent == chosen


def test_the_next_suggestion_stays_in_the_chosen_folder(window, qt_app, source_pdf, tmp_path):
    """
    Re-suggesting a filename is no reason to move the folder the user picked.
    """
    chosen = tmp_path / "recortes"
    chosen.mkdir()

    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.split_options.set_destination(chosen / "capitulo uno.pdf")
    window.ui.btn_process.click()
    settle(qt_app)

    window.ui.split_options.input_selection.setText("5-7")

    assert window.ui.split_options.destination == chosen / "libro_5-7.pdf"


def test_two_splits_land_in_the_same_chosen_folder(window, qt_app, source_pdf, tmp_path):
    chosen = tmp_path / "recortes"
    chosen.mkdir()

    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    window.ui.split_options.set_destination(chosen / "primero.pdf")
    window.ui.btn_process.click()
    settle(qt_app)

    window.ui.split_options.input_selection.setText("5-7")
    window.ui.btn_process.click()
    settle(qt_app)

    assert sorted(p.name for p in chosen.iterdir()) == ["libro_5-7.pdf", "primero.pdf"]


def test_a_document_folder_is_still_the_default_when_nothing_was_chosen(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")

    assert window.ui.split_options.destination == source_pdf.parent / "libro_1-3.pdf"
# =========================
# Cuántas páginas, mientras se tipea
# =========================

def test_the_hint_counts_the_pages_being_asked_for(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("2-7")

    assert window.ui.split_options.label_hint.text() == "6 páginas"


def test_the_hint_explains_a_range_past_the_last_page(window, qt_app, source_pdf):
    """
    The button used to just go dead, leaving the user to guess whether the
    problem was the syntax, the file or the page count.
    """
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("1-5,20")
    hint = window.ui.split_options.label_hint

    assert hint.text() == "La página 20 no existe: este PDF llega hasta la 12."
    assert hint.objectName() == "ErrorText"


def test_a_range_past_the_last_page_keeps_the_button_disabled(window, qt_app, source_pdf):
    """
    The screen already knows the PDF has twelve pages, so offering to export
    page twenty and answering with a modal is a worse version of the hint.
    """
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("1-5,20")

    assert window.ui.btn_process.isEnabled() is False


def test_the_hint_reports_merged_ranges(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("3-8,1-5")

    assert window.ui.split_options.label_hint.text() == "8 páginas: 1-8"


def test_a_syntax_error_is_explained_in_place(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("abc")
    hint = window.ui.split_options.label_hint

    assert hint.text() == "'abc' no es un número de página."
    assert hint.objectName() == "ErrorText"


def test_a_range_still_being_typed_is_not_painted_as_an_error(window, qt_app, source_pdf):
    """
    "1-5" is reached by way of "1-", so turning the line red there made every
    range flash an error at the person writing it. It still explains what is
    missing, and the button still refuses to run.
    """
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("1-")
    hint = window.ui.split_options.label_hint

    assert hint.text() == "Falta la página en la que termina el rango."
    assert hint.objectName() == "SecondaryText", "No es un error: falta terminar"
    assert window.ui.btn_process.isEnabled() is False


def test_a_finished_but_wrong_range_is_painted_as_an_error(window, qt_app, source_pdf):
    """The counterpart: "-5" is not halfway to anything, it is wrong."""
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("-5")

    assert window.ui.split_options.label_hint.objectName() == "ErrorText"


def test_clearing_the_field_puts_the_hint_back(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("abc")

    window.ui.split_options.input_selection.clear()
    hint = window.ui.split_options.label_hint

    assert hint.text() == selection_feedback.EMPTY_HINT
    assert hint.objectName() == "SecondaryText"


def test_the_hint_is_recomputed_when_another_document_is_loaded(window, qt_app, source_pdf, tmp_path):
    """
    The same text means something different against a 12 page PDF and a 3 page
    one.
    """
    corto = tmp_path / "corto.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    doc.save(corto)
    doc.close()

    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-10")
    assert window.ui.split_options.label_hint.text() == "10 páginas"

    load(window, qt_app, corto)

    assert window.ui.split_options.label_hint.objectName() == "ErrorText"
    assert "hasta la 3" in window.ui.split_options.label_hint.text()


def test_the_extract_screen_counts_the_same_way(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    window.ui.extract_options.input_selection.setText("4-9")

    assert window.ui.extract_options.label_hint.text() == "6 páginas"


def test_the_extract_button_respects_the_page_count(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    window.ui.extract_options.input_selection.setText("1-99")

    assert window.ui.btn_extract_process.isEnabled() is False


# =========================
# Vista previa
# =========================

def test_no_preview_before_a_document_is_open(window):
    assert window.ui.split_preview.label_position.text() == ""
    assert window.ui.split_preview.btn_next.isEnabled() is False


def test_opening_a_pdf_previews_its_first_page(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    preview = window.ui.split_preview

    assert preview.label_position.text() == "Página 1 de 12"
    assert preview.label_image.pixmap().isNull() is False, "Tiene que mostrar una imagen"


def test_the_preview_follows_the_selection(window, qt_app, source_pdf):
    """
    What the user is checking is whether the chapter starts where they think it
    does.
    """
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("7-9")
    settle(qt_app)

    assert window.ui.split_preview.label_position.text() == "Página 7 de 12"


def test_editing_the_range_without_moving_its_start_leaves_the_preview_alone(
    window, qt_app, source_pdf
):
    """
    The condition that makes the panel usable: re-jumping on every keystroke
    would pull the user back every time they looked at the next page.
    """
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("7-9")
    settle(qt_app)

    window.ui.split_preview.btn_next.click()
    settle(qt_app)
    assert window.ui.split_preview.label_position.text() == "Página 8 de 12"

    window.ui.split_options.input_selection.setText("7-11")
    settle(qt_app)

    assert window.ui.split_preview.label_position.text() == "Página 8 de 12"


def test_moving_the_start_of_the_range_moves_the_preview(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("7-9")
    settle(qt_app)

    window.ui.split_options.input_selection.setText("4-9")
    settle(qt_app)

    assert window.ui.split_preview.label_position.text() == "Página 4 de 12"


def test_the_arrows_step_through_the_document(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    window.ui.split_preview.btn_next.click()
    settle(qt_app)
    assert window.ui.split_preview.label_position.text() == "Página 2 de 12"

    window.ui.split_preview.btn_previous.click()
    settle(qt_app)
    assert window.ui.split_preview.label_position.text() == "Página 1 de 12"


def test_the_arrows_stop_at_the_edges(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    preview = window.ui.split_preview

    assert preview.btn_previous.isEnabled() is False, "Está en la primera"

    window.ui.split_options.input_selection.setText("12")
    settle(qt_app)

    assert preview.label_position.text() == "Página 12 de 12"
    assert preview.btn_next.isEnabled() is False, "Está en la última"


def test_the_preview_says_whether_the_page_is_included(window, qt_app, source_pdf):
    """
    The point of looking at a page before splitting: a page number alone does
    not answer it once the selection has several ranges.
    """
    load(window, qt_app, source_pdf)
    preview = window.ui.split_preview

    window.ui.split_options.input_selection.setText("7-9")
    settle(qt_app)
    assert "Entra" in preview.label_membership.text()

    for _ in range(3):
        preview.btn_next.click()
        settle(qt_app)

    assert preview.label_position.text() == "Página 10 de 12"
    assert preview.label_membership.text() == "No entra en la selección"


def test_a_page_inside_a_later_range_counts_as_included(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("1-2,11")
    settle(qt_app)
    window.ui.split_preview.btn_next.click()
    settle(qt_app)

    assert window.ui.split_preview.label_position.text() == "Página 2 de 12"
    assert "Entra" in window.ui.split_preview.label_membership.text()


def test_nothing_is_claimed_about_membership_without_a_selection(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    assert window.ui.split_preview.label_membership.text() == ""


def test_an_unusable_selection_claims_nothing_either(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("7-9")
    settle(qt_app)

    window.ui.split_options.input_selection.setText("7-")
    settle(qt_app)

    assert window.ui.split_preview.label_membership.text() == ""


def test_a_second_document_resets_the_preview(window, qt_app, source_pdf, tmp_path):
    otro = tmp_path / "otro.pdf"
    doc = pymupdf.open()
    for _ in range(4):
        doc.new_page().insert_text((72, 90), "otro", fontsize=20)
    doc.save(otro)
    doc.close()

    load(window, qt_app, source_pdf)
    window.ui.split_preview.btn_next.click()
    settle(qt_app)

    load(window, qt_app, otro)

    assert window.ui.split_preview.label_position.text() == "Página 1 de 4"


def test_a_failed_load_leaves_no_stale_page_on_screen(window, qt_app, source_pdf, tmp_path):
    roto = tmp_path / "roto.pdf"
    roto.write_bytes(b"no soy un pdf")

    load(window, qt_app, source_pdf)
    assert window.ui.split_preview.label_image.pixmap().isNull() is False

    load(window, qt_app, roto)

    assert window.ui.split_preview.label_image.pixmap().isNull() is True
    assert window.ui.split_preview.label_position.text() == ""


def test_a_rendered_page_is_not_rendered_twice(window, qt_app, source_pdf):
    """
    Flipping back through a chapter has to be free; a dense page costs tens of
    milliseconds to paint.
    """
    load(window, qt_app, source_pdf)
    view_model = window._view_model

    window.ui.split_preview.btn_next.click()
    settle(qt_app)
    cached = len(view_model._preview_cache)

    window.ui.split_preview.btn_previous.click()
    settle(qt_app)

    assert len(view_model._preview_cache) == cached, "La página 1 ya estaba renderizada"


def test_the_preview_does_not_block_the_window(window, qt_app, source_pdf):
    """
    A preview is not an export: it must not show the spinner or disable the
    fields, or typing a range would flicker the whole screen.
    """
    load(window, qt_app, source_pdf)

    window.ui.split_preview.btn_next.click()
    busy_during = window.ui.progress.isVisible()
    fields_live = window.ui.split_options.input_selection.isEnabled()
    settle(qt_app)

    assert busy_during is False
    assert fields_live is True


def test_the_position_updates_before_the_image_arrives(window, qt_app, source_pdf):
    """
    Pressing an arrow on a dense page would otherwise look like nothing
    happened until it finished painting.
    """
    load(window, qt_app, source_pdf)

    window.ui.split_preview.btn_next.click()

    assert window.ui.split_preview.label_position.text() == "Página 2 de 12"
def test_a_late_render_does_not_overwrite_a_newer_page(window, qt_app, source_pdf):
    """
    Typing "1-5,10-15" moves the preview several times, and what ends up on
    screen has to be the page last asked for, not the last one to finish
    painting.

    Asserted on the **image** and not on the position label: a stale result
    repaints the picture while the label keeps saying the right number, which is
    exactly the mismatch the guard exists to prevent. The stale bytes are not a
    real PNG, so without the guard the panel drops to its failure state.
    """
    from kobun.application.dto.page_preview import PagePreview

    load(window, qt_app, source_pdf)

    window.ui.split_options.input_selection.setText("5-9")
    settle(qt_app)
    assert window.ui.split_preview.label_image.pixmap().isNull() is False

    view_model = window._view_model
    stale = PagePreview(page_number=2, data=b"no soy un png", width=420, height=594)
    view_model._on_preview_ready(stale, token=view_model._preview_token - 1, target_width=420)

    assert window.ui.split_preview.label_position.text() == "Página 5 de 12"
    assert window.ui.split_preview.label_image.pixmap().isNull() is False, (
        "Un render viejo no debe repintar la página que está en pantalla"
    )


def test_a_late_render_is_still_cached(window, qt_app, source_pdf):
    """
    It cost the same to make, and the user may well come back to that page.
    """
    from kobun.application.dto.page_preview import PagePreview

    load(window, qt_app, source_pdf)
    view_model = window._view_model

    stale = PagePreview(page_number=9, data=b"\x89PNG", width=420, height=594)
    view_model._on_preview_ready(stale, token=view_model._preview_token - 1, target_width=420)

    assert (9, 420) in view_model._preview_cache


def test_a_late_failure_does_not_blank_a_working_page(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    view_model = window._view_model

    view_model._on_preview_failed(RuntimeError("tarde"), token=view_model._preview_token - 1)

    assert window.ui.split_preview.label_image.pixmap().isNull() is False


def test_a_preview_that_fails_is_reported_without_a_dialog(window, qt_app, source_pdf, dialogs):
    """
    A page that cannot be painted is a broken preview, not a failed export, and
    the user did not ask for it in the first place.
    """
    load(window, qt_app, source_pdf)

    source_pdf.unlink()
    window.ui.split_preview.btn_next.click()
    settle(qt_app)

    assert dialogs.errors == []
    assert window.ui.split_preview.label_image.pixmap().isNull() is True
    assert window.ui.label_status.text() != ""
def test_the_arrows_come_back_after_an_export(window, qt_app, source_pdf):
    """
    Regression: the panel used to read the buttons' own state to decide whether
    to re-enable them, and a disabled button always answers "no", so the arrows
    stayed dead for the rest of the session.
    """
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("2-4")
    settle(qt_app)

    window.ui.btn_process.click()
    settle(qt_app)

    preview = window.ui.split_preview
    assert preview.label_position.text() == "Página 2 de 12"
    assert preview.btn_next.isEnabled() is True
    assert preview.btn_previous.isEnabled() is True


def test_the_arrows_freeze_while_an_export_runs(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("2-4")
    settle(qt_app)

    window.ui.btn_process.click()
    frozen = window.ui.split_preview.btn_next.isEnabled()
    settle(qt_app)

    assert frozen is False


def test_freezing_does_not_revive_an_edge_arrow(window, qt_app, source_pdf):
    """
    Coming back from busy restores what the page position allows, not everything.
    """
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("1-3")
    settle(qt_app)

    window.ui.btn_process.click()
    settle(qt_app)

    assert window.ui.split_preview.label_position.text() == "Página 1 de 12"
    assert window.ui.split_preview.btn_previous.isEnabled() is False
# =========================
# Ver la página más grande
# =========================

def test_enlarging_is_offered_only_once_there_is_a_page(window, qt_app, source_pdf):
    assert window.ui.split_preview.btn_enlarge.isEnabled() is False

    load(window, qt_app, source_pdf)

    assert window.ui.split_preview.btn_enlarge.isEnabled() is True


def test_the_enlarge_button_opens_the_window(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)

    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)

    assert window._preview_dialog is not None
    assert window._preview_dialog.isVisible() is True


def test_clicking_the_thumbnail_opens_it_too(window, qt_app, source_pdf):
    """
    A small picture is the obvious thing to click when it is too small to read.
    """
    load(window, qt_app, source_pdf)

    window.ui.split_preview.label_image.clicked.emit()
    settle(qt_app)

    assert window._preview_dialog.isVisible() is True


def test_enlarging_without_a_document_does_nothing(window, qt_app):
    window.ui.split_preview.enlarge_requested.emit()
    settle(qt_app)

    assert window._preview_dialog is None


def test_the_enlarged_view_shows_the_same_page(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_options.input_selection.setText("6-9")
    settle(qt_app)

    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)
    enlarged = window._preview_dialog.preview

    assert enlarged.label_position.text() == "Página 6 de 12"
    assert enlarged.label_image.pixmap().isNull() is False
    assert "Entra" in enlarged.label_membership.text()


def test_the_enlarged_view_offers_no_second_enlarge(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)
    enlarged = window._preview_dialog.preview

    assert enlarged.btn_enlarge.isVisibleTo(enlarged) is False


def test_stepping_in_the_enlarged_view_moves_the_thumbnail(window, qt_app, source_pdf):
    """
    Both are views of the same state, so they can never show different pages.
    """
    load(window, qt_app, source_pdf)
    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)

    window._preview_dialog.preview.btn_next.click()
    settle(qt_app)

    assert window._preview_dialog.preview.label_position.text() == "Página 2 de 12"
    assert window.ui.split_preview.label_position.text() == "Página 2 de 12"


def test_typing_a_range_moves_the_enlarged_view_as_well(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)

    window.ui.split_options.input_selection.setText("11-12")
    settle(qt_app)

    assert window._preview_dialog.preview.label_position.text() == "Página 11 de 12"


def test_the_enlarged_view_asks_for_a_bigger_render(window, qt_app, source_pdf):
    """
    Scaling a thumbnail up is what makes an enlarged view look broken.
    """
    load(window, qt_app, source_pdf)
    thumbnail_width = window._view_model._preview_width

    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)

    assert window._view_model._preview_width > thumbnail_width


def test_closing_it_goes_back_to_the_thumbnail_s_width(window, qt_app, source_pdf):
    """
    So the next jump while typing stays cheap.
    """
    load(window, qt_app, source_pdf)
    thumbnail_width = window._view_model._preview_width

    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)
    window._preview_dialog.close()
    settle(qt_app)

    assert window._view_model._preview_width == thumbnail_width


def test_the_thumbnail_keeps_working_after_the_window_closes(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)
    window._preview_dialog.close()
    settle(qt_app)

    window.ui.split_preview.btn_next.click()
    settle(qt_app)

    assert window.ui.split_preview.label_position.text() == "Página 2 de 12"
    assert window.ui.split_preview.label_image.pixmap().isNull() is False


def test_a_closed_window_is_not_updated_any_more(window, qt_app, source_pdf):
    """
    A hidden view must not be painted: it would hold a pixmap of a page nobody
    is looking at, and every render would be doing twice the work.
    """
    load(window, qt_app, source_pdf)
    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)
    window._preview_dialog.close()
    settle(qt_app)

    stale = window._preview_dialog.preview.label_position.text()
    window.ui.split_options.input_selection.setText("9-10")
    settle(qt_app)

    assert window._preview_dialog.preview.label_position.text() == stale
    assert window.ui.split_preview.label_position.text() == "Página 9 de 12"


def test_reopening_it_catches_up_with_the_current_page(window, qt_app, source_pdf):
    load(window, qt_app, source_pdf)
    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)
    window._preview_dialog.close()
    settle(qt_app)

    window.ui.split_options.input_selection.setText("9-10")
    settle(qt_app)
    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)

    assert window._preview_dialog.preview.label_position.text() == "Página 9 de 12"
    assert window._preview_dialog.preview.label_image.pixmap().isNull() is False


def test_loading_another_document_clears_the_enlarged_view(window, qt_app, source_pdf, tmp_path):
    otro = tmp_path / "otro.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    doc.save(otro)
    doc.close()

    load(window, qt_app, source_pdf)
    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)

    load(window, qt_app, otro)

    assert window._preview_dialog.preview.label_position.text() == "Página 1 de 3"


def test_the_enlarged_view_does_not_block_the_window(window, qt_app, source_pdf):
    """
    Modeless on purpose: it is a bigger look at the same page, not a question
    being asked. A modal one would also have hung this test.
    """
    load(window, qt_app, source_pdf)
    window.ui.split_preview.btn_enlarge.click()
    settle(qt_app)

    window.ui.split_options.input_selection.setText("3-4")
    settle(qt_app)

    assert window.ui.split_options.input_selection.isEnabled() is True
    assert window.ui.btn_process.isEnabled() is True
