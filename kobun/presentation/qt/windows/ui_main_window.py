from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import kobun
from kobun.presentation.qt.windows.drag_drop_area import DragDropArea
from kobun.presentation.qt.windows.export_result_card import ExportResultCard
from kobun.presentation.qt.windows.extract_options_widget import ExtractOptionsWidget
from kobun.presentation.qt.windows.split_options_widget import SplitOptionsWidget

SPLIT_PAGE = 0
EXTRACT_PAGE = 1
HISTORY_PAGE = 2


class Ui_MainWindow:
    """
    Building the interface, with no logic at all.

    The widgets carry no styles of their own: every colour comes from the QSS
    StyleGenerator produces, so switching theme is replacing one stylesheet.
    """

    def setupUi(self, MainWindow) -> None:
        MainWindow.setObjectName("MainWindow")
        MainWindow.setWindowTitle("Kobun")
        MainWindow.resize(1000, 680)

        self.central_widget = QWidget(MainWindow)
        root = QHBoxLayout(self.central_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_content(), stretch=1)

        MainWindow.setCentralWidget(self.central_widget)

    # =========================
    # Sidebar
    # =========================

    def _build_sidebar(self) -> QFrame:
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(224)

        layout = QVBoxLayout(self.sidebar)
        # No horizontal margin: the navigation's accent bar has to touch the
        # panel's edge, like a rail.
        layout.setContentsMargins(0, 26, 0, 22)
        layout.setSpacing(0)

        header = QVBoxLayout()
        header.setContentsMargins(18, 0, 18, 0)
        header.setSpacing(2)

        self.label_logo = QLabel("KOBUN")
        self.label_logo.setObjectName("Logo")
        header.addWidget(self.label_logo)

        self.label_tagline = QLabel("Dividir y extraer")
        self.label_tagline.setObjectName("SecondaryText")
        header.addWidget(self.label_tagline)

        layout.addLayout(header)
        layout.addSpacing(28)

        self.btn_split = self._nav_button("Dividir PDF", checked=True)
        layout.addWidget(self.btn_split)

        self.btn_extract = self._nav_button("Extraer imágenes")
        layout.addWidget(self.btn_extract)

        self.btn_history = self._nav_button("Historial")
        layout.addWidget(self.btn_history)

        layout.addStretch()

        footer = QVBoxLayout()
        footer.setContentsMargins(18, 0, 18, 0)
        footer.setSpacing(6)

        self.label_theme = QLabel("TEMA")
        self.label_theme.setObjectName("SectionLabel")
        footer.addWidget(self.label_theme)

        self.combo_theme = QComboBox()
        footer.addWidget(self.combo_theme)

        # The version comes from the package and not from a constant of its
        # own: that way the downloaded file's name can stay clean while knowing
        # which version is running is still possible from inside the app.
        self.label_version = QLabel(f"v{kobun.__version__}")
        self.label_version.setObjectName("SecondaryText")
        footer.addWidget(self.label_version)

        layout.addLayout(footer)

        return self.sidebar

    @staticmethod
    def _hairline() -> QFrame:
        """One pixel: separates sections without boxing them into a frame."""
        line = QFrame()
        line.setObjectName("Hairline")
        line.setFixedHeight(1)

        return line

    @staticmethod
    def _nav_button(text: str, checked: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("NavButton")
        button.setCheckable(True)
        button.setChecked(checked)
        button.setAutoExclusive(True)

        return button

    # =========================
    # Content
    # =========================

    def _build_content(self) -> QFrame:
        self.content_area = QFrame()
        self.content_area.setObjectName("MainContainer")

        layout = QVBoxLayout(self.content_area)
        layout.setContentsMargins(38, 30, 38, 26)
        layout.setSpacing(18)

        # Order matters: the indices are the SPLIT_PAGE / EXTRACT_PAGE /
        # HISTORY_PAGE constants the window navigates by.
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_split_page())
        self.pages.addWidget(self._build_extract_page())
        self.pages.addWidget(self._build_history_page())
        layout.addWidget(self.pages, stretch=1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate: there is no way to know how much is left.
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.label_status = QLabel("")
        self.label_status.setWordWrap(True)
        layout.addWidget(self.label_status)

        return self.content_area

    def _build_split_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        self.title_split = QLabel("Dividir documento")
        self.title_split.setObjectName("Title")
        layout.addWidget(self.title_split)

        self.drop_area = DragDropArea()
        layout.addWidget(self.drop_area)

        layout.addWidget(self._hairline())

        self.split_options = SplitOptionsWidget()
        layout.addWidget(self.split_options)

        layout.addStretch()

        self.split_result = ExportResultCard()
        layout.addWidget(self.split_result)

        self.btn_process = QPushButton("DIVIDIR PDF")
        self.btn_process.setObjectName("PrimaryButton")
        self.btn_process.setMinimumHeight(44)
        self.btn_process.setEnabled(False)
        layout.addWidget(self.btn_process)

        return page

    def _build_extract_page(self) -> QWidget:
        """
        The extraction screen, deliberately built like the split one: same drop
        area, same shape of options, same result card in the same place. It is
        the same task with a different product, and making it look like a
        different application would be a cost with no benefit.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        self.title_extract = QLabel("Extraer imágenes")
        self.title_extract.setObjectName("Title")
        layout.addWidget(self.title_extract)

        # A second drop area rather than one shared above the pages: both emit
        # into the same handler, so a document loaded on either screen shows up
        # on both, and each page stays readable on its own.
        self.extract_drop_area = DragDropArea()
        layout.addWidget(self.extract_drop_area)

        layout.addWidget(self._hairline())

        self.extract_options = ExtractOptionsWidget()
        layout.addWidget(self.extract_options)

        layout.addStretch()

        self.extract_result = ExportResultCard()
        layout.addWidget(self.extract_result)

        self.btn_extract_process = QPushButton("EXTRAER")
        self.btn_extract_process.setObjectName("PrimaryButton")
        self.btn_extract_process.setMinimumHeight(44)
        self.btn_extract_process.setEnabled(False)
        layout.addWidget(self.btn_extract_process)

        return page

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.title_history = QLabel("Historial de exportaciones")
        self.title_history.setObjectName("Title")
        layout.addWidget(self.title_history)

        self.label_history_hint = QLabel(
            "Doble clic para abrir. Las entradas marcadas con ✗ ya no están en disco."
        )
        self.label_history_hint.setObjectName("SecondaryText")
        layout.addWidget(self.label_history_hint)

        self.list_history = QListWidget()
        self.list_history.setAlternatingRowColors(False)
        layout.addWidget(self.list_history, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()

        self.btn_open_export = QPushButton("Abrir seleccionado")
        self.btn_open_export.setEnabled(False)
        actions.addWidget(self.btn_open_export)

        self.btn_forget_export = QPushButton("Quitar de la lista")
        self.btn_forget_export.setEnabled(False)
        actions.addWidget(self.btn_forget_export)

        self.btn_clear_history = QPushButton("Limpiar historial")
        actions.addWidget(self.btn_clear_history)

        layout.addLayout(actions)

        return page
