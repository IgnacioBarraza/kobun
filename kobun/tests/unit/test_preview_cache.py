"""
The cache that makes flipping back through a preview free.

Worth its own tests because the two things it must get right are invisible: the
eviction order, and that a page rendered narrow is never handed back for a wide
panel.
"""
import pytest

from kobun.application.dto.page_preview import PagePreview
from kobun.presentation.preview_cache import PreviewCache

WIDTH = 420


def preview(page_number: int, size: int = 32) -> PagePreview:
    return PagePreview(
        page_number=page_number, data=b"x" * size, width=WIDTH, height=594
    )


@pytest.fixture
def cache():
    return PreviewCache(capacity=3)


def test_a_stored_page_comes_back(cache):
    cache.put(preview(7), WIDTH)

    assert cache.get(7, WIDTH).page_number == 7


def test_a_page_never_rendered_is_absent(cache):
    assert cache.get(7, WIDTH) is None


def test_membership_can_be_asked_for_directly(cache):
    cache.put(preview(7), WIDTH)

    assert (7, WIDTH) in cache
    assert (8, WIDTH) not in cache


def test_storing_the_same_page_twice_does_not_grow_the_cache(cache):
    cache.put(preview(7), WIDTH)
    cache.put(preview(7, size=64), WIDTH)

    assert len(cache) == 1
    assert cache.get(7, WIDTH).size_bytes == 64


# =========================
# El ancho es parte de la identidad
# =========================

def test_a_page_rendered_at_another_width_is_a_different_entry(cache):
    """
    Handing back the narrow render for a wide panel would look like a blurry
    bug.
    """
    cache.put(preview(7), WIDTH)

    assert cache.get(7, 200) is None


def test_both_widths_can_be_held_at_once(cache):
    cache.put(PagePreview(page_number=7, data=b"a", width=200, height=280), 200)
    cache.put(preview(7), WIDTH)

    assert cache.get(7, 200) is not None
    assert cache.get(7, WIDTH) is not None


# =========================
# Desalojo
# =========================

def test_the_cache_does_not_grow_past_its_capacity(cache):
    for page in range(1, 8):
        cache.put(preview(page), WIDTH)

    assert len(cache) == 3


def test_the_oldest_page_is_the_first_to_go(cache):
    for page in (1, 2, 3, 4):
        cache.put(preview(page), WIDTH)

    assert (1, WIDTH) not in cache
    assert (4, WIDTH) in cache


def test_reading_a_page_keeps_it_from_being_evicted(cache):
    """
    The pages being flipped through are the ones worth keeping, and reading is
    the only evidence of that.
    """
    for page in (1, 2, 3):
        cache.put(preview(page), WIDTH)

    cache.get(1, WIDTH)
    cache.put(preview(4), WIDTH)

    assert (1, WIDTH) in cache
    assert (2, WIDTH) not in cache


def test_a_capacity_of_one_still_works():
    cache = PreviewCache(capacity=1)

    cache.put(preview(1), WIDTH)
    cache.put(preview(2), WIDTH)

    assert len(cache) == 1
    assert (2, WIDTH) in cache


def test_a_cache_with_no_room_is_refused():
    with pytest.raises(ValueError, match="at least one page"):
        PreviewCache(capacity=0)


# =========================
# Cambio de documento
# =========================

def test_clearing_forgets_everything(cache):
    """
    The pages of the previous document describe a file that is no longer on
    screen.
    """
    for page in (1, 2):
        cache.put(preview(page), WIDTH)

    cache.clear()

    assert len(cache) == 0
    assert cache.get(1, WIDTH) is None
