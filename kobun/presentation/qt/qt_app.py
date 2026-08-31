import sys
from typing import List, Optional

from PySide6.QtWidgets import QApplication

from kobun.application.services.output_directory_resolver import OutputDirectoryResolver
from kobun.application.services.output_path_resolver import OutputPathResolver
from kobun.application.services.theme_service import ThemeService
from kobun.application.use_cases.extract_assets_use_case import ExtractAssetsUseCase
from kobun.application.use_cases.list_history_use_case import ListHistoryUseCase
from kobun.application.use_cases.load_pdf_use_case import LoadPdfUseCase
from kobun.application.use_cases.record_extraction_use_case import RecordExtractionUseCase
from kobun.application.use_cases.record_split_use_case import RecordSplitUseCase
from kobun.application.use_cases.split_pdf_use_case import SplitPdfUseCase
from kobun.domain.pdf.services.asset_extractor_service import AssetExtractorService
from kobun.domain.pdf.services.pdf_splitter_service import PdfSplitterService
from kobun.infrastructure.config.infrastructure_settings import AppDirectories
from kobun.infrastructure.filesystem.local_file_storage import LocalFileStorage
from kobun.infrastructure.pdf_engine.pdf_document_opener import PdfDocumentOpener
from kobun.infrastructure.pdf_engine.pdf_engine_adapter import PdfEngineAdapter
from kobun.infrastructure.repositories.json_history_repository import JsonHistoryRepository
from kobun.infrastructure.repositories.json_preferences_repository import (
    JsonPreferencesRepository,
)
from kobun.infrastructure.repositories.pdf_asset_extractor_impl import PyMuPdfAssetExtractor
from kobun.infrastructure.repositories.pdf_repository_impl import PyMuPdfRepository
from kobun.infrastructure.ui.theme_loader import JsonThemeSource
from kobun.presentation.qt.app_icon import load_app_icon
from kobun.presentation.qt.cli_arguments import first_pdf_argument
from kobun.presentation.qt.windows.main_window import MainWindow
from kobun.presentation.viewmodels.pdf_view_model import PdfViewModel
from kobun.shared.config.app_settings import (
    APP_ID,
    APP_NAME,
    HISTORY_FILENAME,
    PREFERENCES_FILENAME,
)


class KobunApplication:
    """
    The assembly point: the only place where concrete implementations get
    chosen. Everything else receives its dependencies already built.
    """

    def __init__(self, directories: Optional[AppDirectories] = None):
        self._directories = directories or AppDirectories()

        file_storage = LocalFileStorage()

        # One engine and one opener shared by the repository and the extractor,
        # so both reject the same files with the same messages.
        engine = PdfEngineAdapter()
        opener = PdfDocumentOpener(engine)

        pdf_repository = PyMuPdfRepository(engine, opener)
        asset_extractor = PyMuPdfAssetExtractor(engine, opener)
        pdf_service = PdfSplitterService()
        asset_service = AssetExtractorService()

        self._history_repository = JsonHistoryRepository(
            self._directories.data_file(HISTORY_FILENAME)
        )
        preferences_repository = JsonPreferencesRepository(
            self._directories.config_file(PREFERENCES_FILENAME)
        )

        self._theme_service = ThemeService(preferences_repository, JsonThemeSource())

        self._view_model = PdfViewModel(
            load_use_case=LoadPdfUseCase(pdf_repository, pdf_service),
            split_use_case=SplitPdfUseCase(
                pdf_repository, pdf_service, OutputPathResolver(file_storage)
            ),
            record_use_case=RecordSplitUseCase(self._history_repository),
            list_history_use_case=ListHistoryUseCase(self._history_repository, file_storage),
            file_storage=file_storage,
            extract_use_case=ExtractAssetsUseCase(
                pdf_repository=pdf_repository,
                asset_extractor=asset_extractor,
                asset_service=asset_service,
                output_directory_resolver=OutputDirectoryResolver(file_storage),
                file_storage=file_storage,
            ),
            record_extraction_use_case=RecordExtractionUseCase(self._history_repository),
        )

    def build_window(self) -> MainWindow:
        return MainWindow(self._view_model, self._theme_service, self._history_repository)


def run(argv: Optional[List[str]] = None) -> int:
    """
    Brings the window up and enters Qt's event loop.
    """
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)

    # Fusion is Qt's own style rather than the system's. Without this, part of
    # the QSS gets overridden by the native theme and the window looks
    # different on every machine: this is what let Ubuntu's style show through.
    app.setStyle("Fusion")

    # Declares the desktop app_id. On Wayland it is the only thing that lets
    # the compositor associate the window with its .desktop —and therefore with
    # its icon—; without it the app_id would be "python3".
    app.setDesktopFileName(APP_ID)

    # Still needed on X11 and Windows, where the icon travels with the window
    # instead of being resolved through app_id.
    app.setWindowIcon(load_app_icon())

    window = KobunApplication().build_window()
    window.show()

    # A PDF passed on the command line —or chosen through "Open with" in the
    # file manager— is loaded down the same path as drag & drop, so it inherits
    # its validation and its error handling.
    pdf = first_pdf_argument(argv if argv is not None else sys.argv)
    if pdf is not None:
        window.open_document(pdf)

    return app.exec()
