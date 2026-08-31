from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from kobun.domain.pdf.services.asset_extractor_service import DEFAULT_DPI, MAX_DPI, MIN_DPI
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode
from kobun.domain.pdf.value_objects.overwrite_policy import OverwritePolicy

MODE_LABELS = {
    ExtractionMode.FIGURES: "Las imágenes y figuras de las páginas",
    ExtractionMode.EMBEDDED_IMAGES: "Sólo las imágenes que el PDF tiene guardadas",
    ExtractionMode.PAGE_RASTER: "Cada página completa, como PNG",
}

MODE_HINTS = {
    ExtractionMode.FIGURES: (
        "Saca las imágenes guardadas tal cual están, y además recorta los "
        "gráficos y diagramas dibujados con vectores, que no existen como "
        "imagen dentro del PDF. Es la opción para “dame las figuras”."
    ),
    ExtractionMode.EMBEDDED_IMAGES: (
        "Sólo lo que el PDF guarda como imagen, sin perder calidad y sin que "
        "Kobun dibuje nada. Un gráfico vectorial no va a aparecer."
    ),
    ExtractionMode.PAGE_RASTER: (
        "Dibuja la página entera —texto, vectores e imágenes— en un PNG. "
        "Siempre produce un archivo por página."
    ),
}

POLICY_LABELS = {
    OverwritePolicy.OVERWRITE: "Reemplazar el archivo que ya esté",
    OverwritePolicy.RENAME: "Guardar con un nombre libre",
    OverwritePolicy.FAIL: "Avisar y detenerse",
}

NO_FOLDER = "Elegí un PDF para definir dónde guardar."


class ExtractOptionsWidget(QWidget):
    """
    Mode, page ranges, resolution and destination folder for an extraction.

    Same contract as SplitOptionsWidget: it collects what the user picked and
    parses nothing. The text goes as it is to PageSelection.parse and the
    resolution to the domain, which are the ones that know what is valid.

    The destination is a **folder** and not a file, which is the one real
    difference from the split screen: a single page can produce several images.
    """

    selection_changed = Signal(str)
    mode_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Same split as in SplitOptionsWidget: the field holds the folder's
        # name and the containing directory is reported below, because a full
        # path in the field is unreadable and is not what needs editing.
        self._parent_directory: Optional[Path] = None

        # See SplitOptionsWidget: distinguishing a suggestion from a typed name
        # is what lets the folder follow the range *and* the mode, which is part
        # of its name.
        self._suggested_name: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Qué extraer"))
        self.combo_mode = QComboBox()
        for mode, label in MODE_LABELS.items():
            self.combo_mode.addItem(label, mode)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.combo_mode)

        self.label_mode_hint = QLabel("")
        self.label_mode_hint.setObjectName("SecondaryText")
        self.label_mode_hint.setWordWrap(True)
        layout.addWidget(self.label_mode_hint)

        layout.addSpacing(8)
        layout.addWidget(QLabel("Páginas"))
        self.input_selection = QLineEdit()
        self.input_selection.setPlaceholderText("1-5,10-15  ·  7  ·  20-40")
        self.input_selection.textChanged.connect(self.selection_changed)
        layout.addWidget(self.input_selection)

        self.row_dpi = QWidget()
        dpi_row = QHBoxLayout(self.row_dpi)
        dpi_row.setContentsMargins(0, 6, 0, 0)
        dpi_row.setSpacing(8)

        dpi_row.addWidget(QLabel("Resolución"))
        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(MIN_DPI, MAX_DPI)
        self.spin_dpi.setSingleStep(6)
        self.spin_dpi.setValue(DEFAULT_DPI)
        self.spin_dpi.setSuffix(" dpi")
        dpi_row.addWidget(self.spin_dpi)
        dpi_row.addStretch()

        layout.addWidget(self.row_dpi)

        layout.addSpacing(8)
        layout.addWidget(QLabel("Carpeta de salida"))

        destination_row = QHBoxLayout()
        destination_row.setSpacing(6)

        self.input_output = QLineEdit()
        self.input_output.setPlaceholderText("Se sugiere al abrir el PDF")
        destination_row.addWidget(self.input_output)

        self.btn_browse_output = QPushButton("Examinar")
        self.btn_browse_output.clicked.connect(self._browse_output)
        destination_row.addWidget(self.btn_browse_output)

        layout.addLayout(destination_row)

        self.label_folder = QLabel(NO_FOLDER)
        self.label_folder.setObjectName("SecondaryText")
        self.label_folder.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.label_folder)

        layout.addSpacing(8)
        layout.addWidget(QLabel("Si un archivo ya existe"))
        self.combo_policy = QComboBox()
        for policy, label in POLICY_LABELS.items():
            self.combo_policy.addItem(label, policy)
        layout.addWidget(self.combo_policy)

        self._render_mode()

    # =========================
    # Reading
    # =========================

    @property
    def selection_text(self) -> str:
        return self.input_selection.text().strip()

    @property
    def mode(self) -> ExtractionMode:
        """
        Qt hands item data back as a plain str, so the enum has to be rebuilt.
        Without this the rest of the system gets "page_raster" instead of the
        member.
        """
        return ExtractionMode(self.combo_mode.currentData())

    @property
    def dpi(self) -> int:
        return int(self.spin_dpi.value())

    @property
    def output_name(self) -> str:
        return self.input_output.text().strip()

    @property
    def destination(self) -> Optional[Path]:
        """
        The full folder path: the remembered parent plus the typed name.

        Returns None when there is no name, so the use case falls back to its
        suggested folder.
        """
        name = self.output_name
        if not name or self._parent_directory is None:
            return None

        return self._parent_directory / name

    @property
    def policy(self) -> OverwritePolicy:
        return OverwritePolicy(self.combo_policy.currentData())

    def set_policy(self, policy: OverwritePolicy) -> None:
        for index in range(self.combo_policy.count()):
            if self.combo_policy.itemData(index) == policy:
                self.combo_policy.setCurrentIndex(index)
                return

    def set_mode(self, mode: ExtractionMode) -> None:
        for index in range(self.combo_mode.count()):
            if self.combo_mode.itemData(index) == mode:
                self.combo_mode.setCurrentIndex(index)
                return

    # =========================
    # Writing
    # =========================

    def set_parent_directory(self, directory: Optional[Path]) -> None:
        """
        Where the output folder gets created. Set when a document loads, and
        the folder dialog can change it.
        """
        self._parent_directory = Path(directory) if directory is not None else None
        self._render_folder()

    def set_destination(self, path: Path) -> None:
        """
        Sets parent and folder name from a full path.
        """
        path = Path(path)
        self.set_parent_directory(path.parent)
        self.input_output.setText(path.name)

    def set_suggested_destination(self, path: Optional[Path]) -> None:
        """
        Prefills the suggestion, replacing an earlier suggestion but never
        something the user typed.
        """
        if path is None:
            return

        current = self.output_name
        if current and current != self._suggested_name:
            return

        self.set_destination(path)
        self._suggested_name = path.name

    def clear(self) -> None:
        self.input_selection.clear()
        self.input_output.clear()
        self._suggested_name = None

    def set_enabled(self, enabled: bool) -> None:
        self.combo_mode.setEnabled(enabled)
        self.input_selection.setEnabled(enabled)
        self.spin_dpi.setEnabled(enabled)
        self.input_output.setEnabled(enabled)
        self.btn_browse_output.setEnabled(enabled)
        self.combo_policy.setEnabled(enabled)

    # =========================
    # Internals
    # =========================

    def _on_mode_changed(self, _index: int) -> None:
        self._render_mode()
        self.mode_changed.emit(self.mode)

    def _render_mode(self) -> None:
        mode = self.mode
        self.label_mode_hint.setText(MODE_HINTS[mode])
        # The resolution only means something when Kobun is the one painting the
        # pixels, which now includes cropping a vector figure. A stored image
        # comes out at whatever it was stored at.
        self.row_dpi.setVisible(mode.renders_anything)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_folder()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._render_folder()

    def _render_folder(self) -> None:
        if self._parent_directory is None:
            self.label_folder.setText(NO_FOLDER)
            self.label_folder.setToolTip("")
            return

        full = str(self._parent_directory)
        metrics = QFontMetrics(self.label_folder.font())
        available = max(self.width() - 90, 120)

        self.label_folder.setText(
            f"Dentro de: {metrics.elidedText(full, Qt.TextElideMode.ElideMiddle, available)}"
        )
        self.label_folder.setToolTip(full)

    def _browse_output(self) -> None:
        current = self.destination or self._parent_directory or Path.home()
        directory = QFileDialog.getExistingDirectory(
            self, "Elegir carpeta de salida", str(current)
        )

        if directory:
            self.set_destination(Path(directory))
