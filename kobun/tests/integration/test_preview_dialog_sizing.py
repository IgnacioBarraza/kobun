"""
How the enlarged view sizes itself.

Pure arithmetic over the numbers the dialog is given, kept out of the Qt tests
because it is the part that is easy to get wrong and easy to check: a page's
shape decides the window's shape, and the requested render resolution has to
match what will actually be displayed.

Lives under integration because it needs PySide6 to instantiate the dialog, and
`unit/` is the suite that has to keep running with nothing installed.
"""
import os

import pytest

pytest.importorskip("PySide6", reason="PySide6 no instalado")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from kobun.application.use_cases.render_page_preview_use_case import (  # noqa: E402
    MAX_PREVIEW_WIDTH,
    MIN_PREVIEW_WIDTH,
)
from kobun.presentation.qt.windows.page_preview_dialog import (  # noqa: E402
    A4_ASPECT,
    CHROME_HEIGHT,
    WIDTH_STEP,
    PagePreviewDialog,
)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def reference(qt_app):
    window = QWidget()
    window.resize(1180, 820)

    yield window

    window.close()


@pytest.fixture
def dialog(qt_app, reference):
    dialog = PagePreviewDialog(reference)

    yield dialog

    dialog.close()


# =========================
# Forma de la ventana
# =========================

def test_a_portrait_page_gets_a_taller_window_than_wide(dialog, reference):
    dialog.size_to(reference, A4_ASPECT)

    assert dialog.height() > dialog.width()


def test_a_landscape_page_gets_a_wider_window_than_tall(dialog, reference):
    """
    A fixed rectangle left a landscape page stranded between two margins.
    """
    dialog.size_to(reference, 842 / 595)

    assert dialog.width() > dialog.height()


def test_the_window_follows_the_page_s_proportions(dialog, reference):
    dialog.size_to(reference, A4_ASPECT)

    page_height = dialog.height() - CHROME_HEIGHT
    implied_width = page_height * A4_ASPECT

    assert dialog.width() == pytest.approx(implied_width, abs=WIDTH_STEP)


def test_a_nonsense_aspect_falls_back_to_a_page_shape(dialog, reference):
    for aspect in (0, -1):
        dialog.size_to(reference, aspect)

        assert dialog.height() > dialog.width()


def test_the_window_never_goes_below_its_minimum(dialog, reference):
    tiny = QWidget()
    tiny.resize(200, 200)

    dialog.size_to(tiny, A4_ASPECT)

    assert dialog.width() >= dialog.minimumWidth()
    assert dialog.height() >= dialog.minimumHeight()
    tiny.close()


def test_sizing_without_a_window_to_centre_on_still_works(dialog):
    """
    The screen is what bounds the size; the main window only says where to put
    it. With no window there is nothing to centre on, and the size is still
    sane rather than left at whatever Qt defaulted to.
    """
    dialog.size_to(None, A4_ASPECT)

    assert dialog.width() >= dialog.minimumWidth()
    assert dialog.height() >= dialog.minimumHeight()


# =========================
# Resolución pedida
# =========================

def test_the_requested_width_covers_what_will_be_displayed(dialog, reference):
    dialog.size_to(reference, A4_ASPECT)
    dialog.show()

    requested = dialog.desired_render_width()

    assert requested >= dialog.preview.label_image.width()


def test_the_requested_width_is_rounded_to_a_step(dialog, reference):
    """
    A window being dragged would otherwise ask for a slightly different render
    on every frame, and a dense page costs a quarter of a second to paint.
    """
    dialog.size_to(reference, A4_ASPECT)
    dialog.show()

    assert dialog.desired_render_width() % WIDTH_STEP == 0


def test_the_requested_width_stays_within_what_the_use_case_accepts(dialog, reference):
    huge = QWidget()
    huge.resize(9000, 9000)
    dialog.size_to(huge, A4_ASPECT)

    requested = dialog.desired_render_width()

    assert MIN_PREVIEW_WIDTH <= requested <= MAX_PREVIEW_WIDTH
    huge.close()


def test_a_width_is_reported_even_before_the_layout_runs(dialog, reference):
    """
    The window asks for its resolution the moment it opens, which is before Qt
    has given the label a size.
    """
    dialog.size_to(reference, A4_ASPECT)

    assert dialog.desired_render_width() >= MIN_PREVIEW_WIDTH
