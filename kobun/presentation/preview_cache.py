"""
Remembering the pages already rendered.

Navigating a preview goes back and forth over the same few pages, and a dense
page costs tens of milliseconds to paint. Keeping the last handful means the
second look is free.

Bounded on purpose: a 600 page book previewed end to end would otherwise hold
600 thumbnails in memory. Free of Qt so the eviction order can be tested without
a window.
"""
from collections import OrderedDict
from typing import Optional

from kobun.application.dto.page_preview import PagePreview

DEFAULT_CAPACITY = 12
"""Enough to cover flipping around a chapter, at roughly 40 KB a page."""


class PreviewCache:
    """
    Least-recently-used cache of rendered pages, keyed by page number and the
    width it was rendered at.

    The width is part of the key because the same page rendered narrow and wide
    are different pictures, and handing back the narrow one for a wide panel
    would look like a blurry bug.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY):
        if capacity < 1:
            raise ValueError("A preview cache needs room for at least one page.")

        self._capacity = capacity
        self._entries: "OrderedDict[tuple, PagePreview]" = OrderedDict()

    def get(self, page_number: int, target_width: int) -> Optional[PagePreview]:
        key = (page_number, target_width)
        preview = self._entries.get(key)

        if preview is not None:
            # Touched, so the pages being flipped through are the last to go.
            self._entries.move_to_end(key)

        return preview

    def put(self, preview: PagePreview, target_width: int) -> None:
        key = (preview.page_number, target_width)
        self._entries[key] = preview
        self._entries.move_to_end(key)

        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        """
        Called when the document changes: the pages of the previous one describe
        a file that is no longer on screen.
        """
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key) -> bool:
        """`(page_number, target_width) in cache`."""
        return tuple(key) in self._entries
