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
    QVBoxLayout,
    QWidget,
)

from kobun.domain.pdf.value_objects.overwrite_policy import OverwritePolicy
from kobun.domain.pdf.services.pdf_splitter_service import PDF_SUFFIX

POLICY_LABELS = {
    OverwritePolicy.FAIL: "Avisar si el archivo ya existe",
    OverwritePolicy.RENAME: "Guardar con un nombre libre",
    OverwritePolicy.OVERWRITE: "Reemplazar el archivo existente",
}

NO_FOLDER = "Elegí un PDF para definir la carpeta de destino."


class SplitOptionsWidget(QWidget):
    """
    Page ranges, destination and overwrite policy.

    It only collects what the user types; it neither validates nor parses. The
    text goes as it is to PageSelection.parse and the path to the output
    policy, which are the ones that know what is valid.
    """

    selection_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        # The field shows only the filename; the folder is kept apart and
        # reported below. Showing the full path in the field made it unreadable,
        # and it is not what the user needs to edit.
        self._directory: Optional[Path] = None

        # The last name Kobun suggested. Without it there is no way to tell a
        # suggestion apart from something the user typed, and the field could
        # only ever be filled once: changing the range afterwards left the file
        # named after the previous one.
        self._suggested_name: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Páginas a extraer"))
        self.input_selection = QLineEdit()
        self.input_selection.setPlaceholderText("1-5,10-15  ·  7  ·  20-40")
        self.input_selection.textChanged.connect(self.selection_changed)
        layout.addWidget(self.input_selection)

        self.label_hint = QLabel("Separá los rangos con comas.")
        self.label_hint.setObjectName("SecondaryText")
        layout.addWidget(self.label_hint)

        layout.addSpacing(8)
        layout.addWidget(QLabel("Nombre del archivo"))

        destination_row = QHBoxLayout()
        destination_row.setSpacing(6)

        self.input_output = QLineEdit()
        self.input_output.setPlaceholderText("Se sugiere al elegir las páginas")
        destination_row.addWidget(self.input_output)

        self.btn_browse_output = QPushButton("Examinar")
        self.btn_browse_output.clicked.connect(self._browse_output)
        destination_row.addWidget(self.btn_browse_output)

        layout.addLayout(destination_row)

        self.label_folder = QLabel(NO_FOLDER)
        self.label_folder.setObjectName("SecondaryText")
        # Ignored horizontally: without this the sizeHint of a long path
        # expands the layout past the window and the text gets cut against the
        # edge instead of being elided with an ellipsis.
        self.label_folder.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.label_folder)

        layout.addSpacing(8)
        layout.addWidget(QLabel("Si el destino ya existe"))
        self.combo_policy = QComboBox()
        for policy, label in POLICY_LABELS.items():
            self.combo_policy.addItem(label, policy)
        layout.addWidget(self.combo_policy)

    # =========================
    # Reading
    # =========================

    @property
    def selection_text(self) -> str:
        return self.input_selection.text().strip()

    @property
    def output_name(self) -> str:
        return self.input_output.text().strip()

    @property
    def destination(self) -> Optional[Path]:
        """
        The full path to write: the remembered folder plus the typed name.

        Returns None when there is no name, so the use case falls back to its
        suggested path. It appends the extension if missing: the field asks for
        a name, so demanding the user type ".pdf" would be an avoidable error.
        """
        name = self.output_name
        if not name or self._directory is None:
            return None

        if Path(name).suffix.lower() != PDF_SUFFIX:
            name = f"{name}{PDF_SUFFIX}"

        return self._directory / name

    @property
    def policy(self) -> OverwritePolicy:
        """
        Qt stores item data as a QVariant and hands the enum back as a plain
        str, so it has to be rebuilt. Without this the rest of the system gets
        "rename" instead of OverwritePolicy.RENAME.
        """
        return OverwritePolicy(self.combo_policy.currentData())

    def set_policy(self, policy: OverwritePolicy) -> None:
        for index in range(self.combo_policy.count()):
            if self.combo_policy.itemData(index) == policy:
                self.combo_policy.setCurrentIndex(index)
                return

    # =========================
    # Writing
    # =========================

    def set_directory(self, directory: Optional[Path]) -> None:
        """
        The folder to write into. Set when a document loads, and the save
        dialog can change it.
        """
        self._directory = Path(directory) if directory is not None else None
        self._render_folder()

    def set_destination(self, path: Path) -> None:
        """
        Sets folder and name from a full path.
        """
        path = Path(path)
        self.set_directory(path.parent)
        self.input_output.setText(path.name)

    def set_suggested_destination(self, path: Optional[Path]) -> None:
        """
        Prefills the suggested destination, replacing an earlier suggestion but
        never something the user typed.

        The distinction is what makes the field track the range: typing "1-3"
        and then correcting it to "1-4" has to rename the output, while a name
        chosen by hand must survive every later keystroke in the range field.
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
        self.input_selection.setEnabled(enabled)
        self.input_output.setEnabled(enabled)
        self.btn_browse_output.setEnabled(enabled)
        self.combo_policy.setEnabled(enabled)

    def resizeEvent(self, event) -> None:
        # A folder path can be extremely long; it is elided to the available
        # width so it does not widen the window.
        super().resizeEvent(event)
        self._render_folder()

    def showEvent(self, event) -> None:
        # When the folder was set the layout had not run yet, so the available
        # width was the initial one. It is recomputed once geometry is real.
        super().showEvent(event)
        self._render_folder()

    def _render_folder(self) -> None:
        if self._directory is None:
            self.label_folder.setText(NO_FOLDER)
            self.label_folder.setToolTip("")
            return

        full = str(self._directory)
        metrics = QFontMetrics(self.label_folder.font())
        # Measured against the containing widget's width: the label's own is
        # "Ignored", so it reflects no useful limit.
        available = max(self.width() - 90, 120)

        self.label_folder.setText(
            f"Carpeta: {metrics.elidedText(full, Qt.TextElideMode.ElideMiddle, available)}"
        )
        self.label_folder.setToolTip(full)

    def _browse_output(self) -> None:
        current = self.destination or self._directory or Path.home()
        filename, _ = QFileDialog.getSaveFileName(
            self, "Guardar PDF como", str(current), "Documentos PDF (*.pdf)"
        )

        if filename:
            self.set_destination(Path(filename))
