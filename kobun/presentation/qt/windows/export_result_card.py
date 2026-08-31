from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

OPEN_FILE_TEXT = "Abrir PDF"
OPEN_FOLDER_TEXT = "Abrir carpeta"

NOTHING_TITLE = "No había nada para extraer"


class ExportResultCard(QFrame):
    """
    What came out of the last export, with something to do about it.

    It replaces reporting success as a green line in the status bar. The line
    said the export worked; it did not let anyone reach the file, which meant
    the only way to open what you had just made was switching to the history
    tab. That was the actual complaint behind "let me know better when it's
    done".

    Hidden until there is a result, and hidden again as soon as a new operation
    starts: a card describing the previous export while the next one runs is
    worse than no card.
    """

    open_requested = Signal()
    reveal_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ResultCard")
        self.setVisible(False)

        self._detail_text = ""

        # Whether the detail line is a path —elided in the middle so it never
        # widens the window— or prose, which has to wrap: a sentence explaining
        # what to try next is useless with its middle replaced by an ellipsis.
        self._elide_detail = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(3)

        self.label_title = QLabel("")
        self.label_title.setObjectName("ResultTitle")
        self.label_title.setWordWrap(True)
        layout.addWidget(self.label_title)

        self.label_detail = QLabel("")
        self.label_detail.setObjectName("SecondaryText")
        # Ignored horizontally for the same reason as the destination folder
        # label: a long path must elide instead of widening the window.
        self.label_detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.label_detail)

        layout.addSpacing(10)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.btn_open = QPushButton(OPEN_FILE_TEXT)
        actions.addWidget(self.btn_open)

        self.btn_reveal = QPushButton(OPEN_FOLDER_TEXT)
        actions.addWidget(self.btn_reveal)

        actions.addStretch()
        layout.addLayout(actions)

        self.btn_open.clicked.connect(self.open_requested)
        self.btn_reveal.clicked.connect(self.reveal_requested)

    # =========================
    # Presentation
    # =========================

    def show_result(
        self,
        title: str,
        detail: str,
        open_text: str = OPEN_FILE_TEXT,
        can_open: bool = True,
    ) -> None:
        """
        :param title: What was produced, usually the filename or folder name.
        :param detail: One line underneath: counts, size, location.
        :param open_text: Label for the primary action, which is "open the PDF"
            for a split and "open the folder" for an extraction.
        :param can_open: False hides the primary action, for the case where
            there is no single file to open.
        """
        self.label_title.setText(f"✓  {title}")
        self.btn_open.setText(open_text)
        self.btn_open.setVisible(can_open)
        self.btn_reveal.setVisible(True)

        self._set_detail(detail, elide=True)
        self.setVisible(True)

    def show_nothing_found(self, detail: str) -> None:
        """
        An extraction that ran fine and found nothing.

        Not an error —nothing failed and there is nothing to fix— so it is
        reported here rather than through a dialog. The buttons go away because
        there is nothing to open: no folder was left behind.
        """
        self.label_title.setText(NOTHING_TITLE)
        self.btn_open.setVisible(False)
        self.btn_reveal.setVisible(False)

        self._set_detail(detail, elide=False)
        self.setVisible(True)

    def clear(self) -> None:
        self.label_title.clear()
        self.label_detail.clear()
        self._detail_text = ""
        self.setVisible(False)

    # =========================
    # Internals
    # =========================

    def _set_detail(self, detail: str, elide: bool = True) -> None:
        self._detail_text = detail
        self._elide_detail = elide
        self.label_detail.setWordWrap(not elide)
        self.label_detail.setToolTip(detail if elide else "")
        self._render_detail()

    def _render_detail(self) -> None:
        if not self._detail_text:
            self.label_detail.clear()
            return

        if not self._elide_detail:
            self.label_detail.setText(self._detail_text)
            return

        metrics = QFontMetrics(self.label_detail.font())
        # Measured against the card, because the label's own width policy is
        # "Ignored" and therefore reports no useful limit.
        available = max(self.width() - 42, 120)

        self.label_detail.setText(
            metrics.elidedText(self._detail_text, Qt.TextElideMode.ElideMiddle, available)
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_detail()

    def showEvent(self, event) -> None:
        # On the first show the layout has not run, so the width used to elide
        # was the initial one. Recomputed once the geometry is real.
        super().showEvent(event)
        self._render_detail()
