from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from kobun.presentation.qt import styling

NO_DOCUMENT = "Abrí un PDF para ver sus páginas."
RENDERING = "Generando la vista…"
FAILED = "No se pudo mostrar esta página."

INCLUDED = "✓  Entra en la selección"
EXCLUDED = "No entra en la selección"

ENLARGE_TEXT = "Ver más grande"
ENLARGE_TOOLTIP = "Abre la página en una ventana aparte, al tamaño real de lectura."


PREVIOUS_TEXT = "◂"
NEXT_TEXT = "▸"

PAGE_EDGE = QColor(0, 0, 0, 46)
"""A translucent outline drawn around the page.

Translucent black rather than a theme colour because it has to do two jobs: give
a white page an edge against the light themes' near-white surface, and disappear
against the dark ones, where the page itself already is the contrast.

Painted into the pixmap and not set as a border on the label: a label showing a
portrait page is wider and taller than the page, so a border on it would frame
the empty space instead of the picture."""

MINIMUM_WIDTH = 232
"""Narrow enough to sit beside the options, wide enough that a page's headings
and layout are recognisable. A thumbnail is for recognising a page; reading it
is what the enlarged view is for."""



class _ClickableLabel(QLabel):
    """
    A label that reports clicks.

    The thumbnail is the obvious thing to click when it is too small to read, so
    it has to do what clicking a small picture does everywhere else. The button
    beside it stays, because a picture that happens to be clickable is not
    something anyone can see.
    """

    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)

        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class PagePreviewWidget(QFrame):
    """
    What a page looks like, before committing to an export.

    The panel owns no rendering and no page numbers of its own: it asks to move
    and is told what to show. That keeps the decision of *which* page belongs to
    the selection —and the render itself, which happens on a worker— out of a
    widget.

    The image is rendered once at a generous width and scaled down to fit
    whatever room the panel has, so resizing the window costs no re-render.
    """

    previous_requested = Signal()
    next_requested = Signal()
    enlarge_requested = Signal()

    def __init__(self, parent=None, compact: bool = True):
        """
        :param compact: True for the panel beside the options, which offers to
            enlarge itself. False for the enlarged view, which is already as big
            as it gets and would only be offering to open itself again.
        """
        super().__init__(parent)
        self.setObjectName("PreviewPanel")
        self._compact = compact

        if compact:
            self.setMinimumWidth(MINIMUM_WIDTH)

        self._pixmap: Optional[QPixmap] = None

        # Where in the document the panel is. Kept here rather than read back off
        # the buttons: asking a disabled button whether it should be enabled
        # always answers no, which left the arrows dead after an export.
        self._page_number = 0
        self._page_count = 0
        self._enabled = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)

        self.label_title = QLabel("Vista previa")
        self.label_title.setObjectName("SectionLabel")
        header.addWidget(self.label_title)
        header.addStretch()

        self.btn_enlarge = QPushButton(ENLARGE_TEXT)
        self.btn_enlarge.setObjectName("LinkButton")
        self.btn_enlarge.setToolTip(ENLARGE_TOOLTIP)
        self.btn_enlarge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_enlarge.setVisible(compact)
        self.btn_enlarge.setEnabled(False)
        self.btn_enlarge.clicked.connect(self.enlarge_requested)
        header.addWidget(self.btn_enlarge)

        layout.addLayout(header)

        self.label_image = _ClickableLabel(NO_DOCUMENT)
        self.label_image.setObjectName("PreviewImage")
        self.label_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_image.setWordWrap(True)
        # Ignored in both directions: the pixmap is scaled to the label instead
        # of the label growing to the pixmap, which is what keeps a tall page
        # from pushing the window past the screen.
        self.label_image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout.addWidget(self.label_image, stretch=1)

        if compact:
            self.label_image.setCursor(Qt.CursorShape.PointingHandCursor)
            self.label_image.setToolTip(ENLARGE_TOOLTIP)
            self.label_image.clicked.connect(self.enlarge_requested)

        self.label_membership = QLabel("")
        self.label_membership.setObjectName("SecondaryText")
        self.label_membership.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label_membership)

        navigation = QHBoxLayout()
        navigation.setSpacing(6)

        self.btn_previous = QPushButton(PREVIOUS_TEXT)
        self.btn_previous.setObjectName("StepButton")
        self.btn_previous.setEnabled(False)
        self.btn_previous.clicked.connect(self.previous_requested)
        navigation.addWidget(self.btn_previous)

        self.label_position = QLabel("")
        self.label_position.setObjectName("SecondaryText")
        self.label_position.setAlignment(Qt.AlignmentFlag.AlignCenter)
        navigation.addWidget(self.label_position, stretch=1)

        self.btn_next = QPushButton(NEXT_TEXT)
        self.btn_next.setObjectName("StepButton")
        self.btn_next.setEnabled(False)
        self.btn_next.clicked.connect(self.next_requested)
        navigation.addWidget(self.btn_next)

        layout.addLayout(navigation)

    # =========================
    # Presentation
    # =========================

    def show_page(self, page_number: int, page_count: int) -> None:
        """
        Labels the panel for a page whose image has not arrived yet.

        Called before the render starts so the position updates immediately:
        pressing ▸ on a dense page would otherwise look like nothing happened
        for the fifty milliseconds it takes to paint.
        """
        self._page_number = page_number
        self._page_count = page_count

        self.label_position.setText(f"Página {page_number} de {page_count}")
        self.btn_enlarge.setEnabled(page_count > 0)
        self._refresh_navigation()

        if self._pixmap is None:
            self._show_message(RENDERING)

    def show_preview(self, preview) -> None:
        """
        :param preview: A `PagePreview`; its bytes are decoded here, which is the
            only place a rendered page becomes something Qt can paint.
        """
        pixmap = QPixmap()

        if not pixmap.loadFromData(preview.data, "PNG"):
            self.show_failure()
            return

        self._pixmap = pixmap
        styling.apply_text_role(self.label_image, "PreviewImage")
        self._render_pixmap()

    def show_failure(self) -> None:
        self._pixmap = None
        self._show_message(FAILED, error=True)

    def show_membership(self, included: Optional[bool]) -> None:
        """
        Whether the page on screen is one of the pages that will be exported.

        The point of looking at a page before splitting is knowing whether it is
        in or out, and a page number alone does not answer that once the
        selection has several ranges.

        :param included: None when there is no usable selection to compare
            against, which leaves the line blank rather than claiming anything.
        """
        if included is None:
            self.label_membership.setText("")
            return

        self.label_membership.setText(INCLUDED if included else EXCLUDED)
        styling.apply_text_role(
            self.label_membership, styling.SUCCESS if included else styling.SECONDARY
        )

    def clear(self) -> None:
        self._pixmap = None
        self._page_number = 0
        self._page_count = 0

        self.label_position.setText("")
        self.label_membership.setText("")
        self.btn_enlarge.setEnabled(False)
        self._refresh_navigation()
        self._show_message(NO_DOCUMENT)

    def set_enabled(self, enabled: bool) -> None:
        """
        The arrows go dead while an export runs, like every other control, and
        come back to whatever the page position allows. The image stays visible:
        it is what the user is looking at.
        """
        self._enabled = enabled
        self._refresh_navigation()

    def _refresh_navigation(self) -> None:
        """
        An arrow is live when the document has somewhere to go in that direction
        and nothing is running.
        """
        self.btn_previous.setEnabled(self._enabled and self._page_number > 1)
        self.btn_next.setEnabled(
            self._enabled and 0 < self._page_number < self._page_count
        )

    # =========================
    # Internals
    # =========================

    def _show_message(self, message: str, error: bool = False) -> None:
        self.label_image.setPixmap(QPixmap())
        self.label_image.setText(message)
        styling.apply_text_role(
            self.label_image, styling.ERROR if error else "PreviewImage"
        )

    def _render_pixmap(self) -> None:
        """
        Scales the rendered page into the space the panel actually has,
        preserving its proportions.
        """
        if self._pixmap is None:
            return

        available = self.label_image.size()
        if available.width() <= 1 or available.height() <= 1:
            # Laid out but not yet sized; showEvent comes back for this.
            return

        self.label_image.setText("")
        self.label_image.setPixmap(
            self._with_edge(
                self._pixmap.scaled(
                    available,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        )

    @staticmethod
    def _with_edge(pixmap: QPixmap) -> QPixmap:
        """
        The page with a hairline around it, so it reads as a sheet rather than as
        a picture bleeding into the panel.
        """
        framed = QPixmap(pixmap)
        painter = QPainter(framed)

        try:
            painter.setPen(QPen(PAGE_EDGE, 1))
            painter.drawRect(0, 0, framed.width() - 1, framed.height() - 1)
        finally:
            painter.end()

        return framed

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_pixmap()

    def showEvent(self, event) -> None:
        # On the first show the layout has not run, so the label had no real size
        # to scale into.
        super().showEvent(event)
        self._render_pixmap()
