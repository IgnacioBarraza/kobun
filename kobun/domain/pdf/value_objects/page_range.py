from dataclasses import dataclass

from kobun.domain.pdf.exceptions.invalid_page_range_exception import InvalidPageRangeException

# Dashes that tend to appear when copying ranges from a PDF or a browser.
_DASHES = ("–", "—", "−")

MISSING_FIRST_PAGE = "Falta la página en la que empieza el rango."
MISSING_LAST_PAGE = "Falta la página en la que termina el rango."
MISSING_ONLY_PAGE = "Escribí un número de página."


@dataclass(frozen=True)
class PageRange:
    """
    A contiguous page range, 1-based and inclusive at both ends.
    """
    start: int
    end: int

    def __post_init__(self) -> None:
        # The numbers are deliberately left out of this one: a lone "0" becomes
        # the range 0-0, and answering "el rango 0-0 es inválido" to someone who
        # typed a single character shows them an internal shape they never wrote.
        if self.start <= 0 or self.end <= 0:
            raise InvalidPageRangeException("Las páginas se cuentan desde 1.")

        # Says what to type, not just what is wrong: the fix is always the same
        # two numbers the other way round, so there is no reason to make anyone
        # work it out.
        if self.start > self.end:
            raise InvalidPageRangeException(
                f"{self.start}-{self.end} está al revés: escribí {self.end}-{self.start}."
            )

    @classmethod
    def parse(cls, text: str) -> "PageRange":
        """
        Builds a range from text: "12" (a single page) or "1-5".

        :raises InvalidPageRangeException: If the text is not a valid range.
        """
        raw = text.strip()
        for dash in _DASHES:
            raw = raw.replace(dash, "-")

        if not raw:
            raise InvalidPageRangeException(MISSING_ONLY_PAGE)

        parts = raw.split("-")

        if len(parts) == 1:
            page = cls._parse_page(parts[0], MISSING_ONLY_PAGE)
            return cls(start=page, end=page)

        if len(parts) == 2:
            # Each half names itself, so a half-typed range says which number is
            # missing instead of the same sentence for both ends.
            return cls(
                start=cls._parse_page(parts[0], MISSING_FIRST_PAGE),
                end=cls._parse_page(parts[1], MISSING_LAST_PAGE),
            )

        raise InvalidPageRangeException(
            f"No se entiende '{text.strip()}'. Probá con 7 o con 1-5."
        )

    @staticmethod
    def _parse_page(value: str, missing_message: str) -> int:
        """
        :param missing_message: What to say when this half is not there. It
            depends on which half it is, which only the caller knows.
        """
        stripped = value.strip()

        # A missing half —"1-" while still typing— deserves its own message:
        # reporting that '' is not a valid number reads like a bug.
        if not stripped:
            raise InvalidPageRangeException(missing_message)

        # The offending text once, not twice: whoever reads this has the field
        # they typed it into right above the message.
        if not stripped.isdigit():
            raise InvalidPageRangeException(f"'{stripped}' no es un número de página.")

        return int(stripped)

    @property
    def total_pages(self) -> int:
        return self.end - self.start + 1

    def contains(self, page: int) -> bool:
        return self.start <= page <= self.end

    def overlaps_or_touches(self, other: "PageRange") -> bool:
        """
        True if the two ranges overlap or are contiguous (1-5 and 6-10), that
        is, if they can be merged without altering the resulting set of pages.
        """
        return self.start <= other.end + 1 and other.start <= self.end + 1

    def merge(self, other: "PageRange") -> "PageRange":
        """
        Merges two overlapping or contiguous ranges into one.

        :raises InvalidPageRangeException: If the ranges are disjoint.
        """
        if not self.overlaps_or_touches(other):
            raise InvalidPageRangeException(f"No se pueden unir rangos separados: {self} y {other}.")
        return PageRange(start=min(self.start, other.start), end=max(self.end, other.end))

    def __str__(self) -> str:
        if self.start == self.end:
            return str(self.start)
        return f"{self.start}-{self.end}"

    def to_range(self) -> range:
        return range(self.start, self.end + 1)
