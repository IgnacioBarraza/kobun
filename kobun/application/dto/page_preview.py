from dataclasses import dataclass


@dataclass(frozen=True)
class PagePreview:
    """
    One page painted small, to be looked at before committing to an export.

    It carries bytes and not a path because a preview is never written to disk:
    it exists to be shown and then thrown away. PNG so the page's text stays
    legible at thumbnail size, which JPEG artefacts would not.
    """

    page_number: int
    """1-based, same as everywhere else in Kobun."""

    data: bytes
    width: int
    height: int

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def aspect_ratio(self) -> float:
        """Width over height. Zero when the render came back degenerate."""
        return self.width / self.height if self.height else 0.0
