from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

from kobun.domain.pdf.exceptions.invalid_page_range_exception import InvalidPageRangeException
from kobun.domain.pdf.value_objects.page_range import PageRange

_SEPARATORS = (";", " ", "\t", "\n")


@dataclass(frozen=True, slots=True)
class PageSelection:
    """
    Immutable Value Object representing the whole page selection the user
    asked for: one or more ranges, for example "1-5,10-15,20".

    The selection is always kept in canonical form: ranges end up sorted, and
    overlapping or contiguous ones merged. That makes two selections
    representing the same set of pages equal ("1-5,3-8" == "1-8") and keeps
    extraction from ever duplicating a page.
    """
    ranges: Tuple[PageRange, ...]

    def __post_init__(self) -> None:
        if not self.ranges:
            raise InvalidPageRangeException("La selección tiene que incluir al menos un rango.")

        object.__setattr__(self, "ranges", self._canonicalize(self.ranges))

    @staticmethod
    def _canonicalize(ranges: Sequence[PageRange]) -> Tuple[PageRange, ...]:
        ordered = sorted(ranges, key=lambda r: (r.start, r.end))

        merged: List[PageRange] = [ordered[0]]
        for current in ordered[1:]:
            if merged[-1].overlaps_or_touches(current):
                merged[-1] = merged[-1].merge(current)
            else:
                merged.append(current)

        return tuple(merged)

    @classmethod
    def parse(cls, text: str) -> "PageSelection":
        """
        Builds a selection from text: "1-5,10-15", "7", "1-3; 8".

        Accepts commas, semicolons or spaces as separators.

        :raises InvalidPageRangeException: If the text is empty or any range is invalid.
        """
        normalized = text.strip()
        for separator in _SEPARATORS:
            normalized = normalized.replace(separator, ",")

        chunks = [chunk for chunk in normalized.split(",") if chunk]
        if not chunks:
            raise InvalidPageRangeException("La selección de páginas no puede estar vacía.")

        return cls(ranges=tuple(PageRange.parse(chunk) for chunk in chunks))

    @classmethod
    def of(cls, *ranges: PageRange) -> "PageSelection":
        """Syntactic sugar to build a selection from already validated ranges."""
        return cls(ranges=tuple(ranges))

    @property
    def max_page(self) -> int:
        """Highest page requested. Used to validate against the document total."""
        return self.ranges[-1].end

    @property
    def min_page(self) -> int:
        return self.ranges[0].start

    @property
    def total_pages(self) -> int:
        """Actual number of pages to extract, with no duplicates."""
        return sum(r.total_pages for r in self.ranges)

    @property
    def is_contiguous(self) -> bool:
        return len(self.ranges) == 1

    def to_pages(self) -> List[int]:
        """
        Sorted list of 1-based pages, with no duplicates.
        """
        pages: List[int] = []
        for p_range in self.ranges:
            pages.extend(p_range.to_range())
        return pages

    def __iter__(self) -> Iterable[PageRange]:
        return iter(self.ranges)

    def __len__(self) -> int:
        return len(self.ranges)

    def __str__(self) -> str:
        return ",".join(str(r) for r in self.ranges)
