from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from kobun.application.use_cases.render_page_preview_use_case import (
    MAX_PREVIEW_WIDTH,
    MIN_PREVIEW_WIDTH,
)
from kobun.presentation.qt.windows.page_preview_widget import PagePreviewWidget

CLOSE_TEXT = "Cerrar"

SCREEN_FRACTION = 0.92
"""How much of the screen's usable height the enlarged view takes.

Measured against the **screen** and not the main window: the point is reading a
page, and the main window is a wide one, so sizing from it produced a landscape
dialog with a narrow page stranded between two margins."""

A4_ASPECT = 595 / 842
"""Width over height, used before a page has been measured."""

CHROME_HEIGHT = 168
"""Vertical room the title, the membership line, the steppers, the close button
and the margins take, which is height the page does not get."""

CHROME_WIDTH = 56

MINIMUM_SIZE = (420, 520)

WIDTH_STEP = 150
"""Requested render widths are rounded up to a multiple of this.

A window being dragged to a new size would otherwise ask for a slightly
different render on every frame, and a dense page costs a quarter of a second to
paint."""


class PagePreviewDialog(QDialog):
    """
    The page, big enough to read.

    **Modeless on purpose.** It is another view of the same preview state, not a
    question being asked: the panel beside the options and this window always
    show the same page, because both are told what to show by the viewmodel. So
    typing a new range moves both, and stepping here moves the thumbnail too.

    That is also why it holds a `PagePreviewWidget` rather than a picture of its
    own — one widget, two sizes, and no second copy of "which page is this and
    is it included".
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vista previa")
        self.setObjectName("PreviewDialog")
        self.setMinimumSize(*MINIMUM_SIZE)

        # Kept out of the way of the parent's layout and freed when the window
        # goes, so closing it does not leave a hidden widget holding a pixmap.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.preview = PagePreviewWidget(compact=False)
        layout.addWidget(self.preview, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch()

        self.btn_close = QPushButton(CLOSE_TEXT)
        self.btn_close.clicked.connect(self.close)
        footer.addWidget(self.btn_close)

        layout.addLayout(footer)

    def size_to(self, reference, aspect_ratio: float = A4_ASPECT) -> None:
        """
        Sizes itself so the page fills the window, and centres on the main one.

        The page's own proportions decide the shape: a portrait page gets a tall
        window and a landscape one a wide window, instead of a fixed rectangle
        with the page marooned in the middle of it.

        :param reference: The main window, used for centring and as the fallback
            bound when no screen can be queried.
        :param aspect_ratio: Width over height of the page being shown.
        """
        if aspect_ratio <= 0:
            aspect_ratio = A4_ASPECT

        bounds = self._available_size(reference)
        if bounds is None:
            return

        limit_width, limit_height = bounds

        # Height first, since pages are usually taller than wide, then the width
        # the page's shape implies.
        page_height = limit_height - CHROME_HEIGHT
        width = int(page_height * aspect_ratio) + CHROME_WIDTH
        height = limit_height

        if width > limit_width:
            # A landscape page, or a narrow screen: the width becomes the limit
            # and the height follows from it.
            width = limit_width
            height = int((width - CHROME_WIDTH) / aspect_ratio) + CHROME_HEIGHT

        self.resize(
            max(width, MINIMUM_SIZE[0]),
            max(min(height, limit_height), MINIMUM_SIZE[1]),
        )
        self._centre_on(reference)

    def desired_render_width(self) -> int:
        """
        How wide the page has to be rendered to fill this window without being
        upscaled.

        A fixed size cannot do this: 900 pixels is wasted on a laptop and visibly
        soft on a 4K panel. The device pixel ratio is part of it, or the page
        would come out blurry on a HiDPI screen where every logical pixel is
        really two.

        Rounded up to WIDTH_STEP and clamped to what the use case accepts.
        """
        available = self.preview.label_image.width()
        if available <= 1:
            # Not laid out yet; the window's own width is the next best thing.
            available = self.width() - CHROME_WIDTH

        physical = int(available * max(self.devicePixelRatioF(), 1.0))
        stepped = -(-physical // WIDTH_STEP) * WIDTH_STEP

        return max(MIN_PREVIEW_WIDTH, min(stepped, MAX_PREVIEW_WIDTH))

    def _available_size(self, reference):
        """
        How much room there is to grow into: the screen's usable area, falling
        back to the main window when there is no screen to ask (offscreen runs).
        """
        screen = self.screen() or (reference.screen() if reference is not None else None)

        if screen is not None:
            usable = screen.availableGeometry()
            return (
                int(usable.width() * SCREEN_FRACTION),
                int(usable.height() * SCREEN_FRACTION),
            )

        if reference is None:
            return None

        return int(reference.width() * SCREEN_FRACTION), int(
            reference.height() * SCREEN_FRACTION
        )

    def _centre_on(self, reference) -> None:
        if reference is None:
            return

        geometry = self.frameGeometry()
        geometry.moveCenter(reference.frameGeometry().center())
        self.move(geometry.topLeft())
