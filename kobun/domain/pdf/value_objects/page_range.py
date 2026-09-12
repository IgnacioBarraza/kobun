from dataclasses import dataclass

from kobun.domain.pdf.exceptions.invalid_page_range_exception import InvalidPageRangeException

# Dashes that tend to appear when copying ranges from a PDF or a browser.
_DASHES = ("–", "—", "−")


@dataclass(frozen=True)
class PageRange:
    """
    A contiguous page range, 1-based and inclusive at both ends.
    """
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start <= 0 or self.end <= 0:
            raise InvalidPageRangeException(f"Rango de páginas inválido: {self.start}-{self.end}. Las páginas se cuentan desde 1.")
        if self.start > self.end:
            raise InvalidPageRangeException(f"La página inicial {self.start} no puede ser mayor que la final {self.end}.")

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
            raise InvalidPageRangeException("El rango de páginas no puede estar vacío.")

        parts = raw.split("-")

        if len(parts) == 1:
            page = cls._parse_page(parts[0], raw)
            return cls(start=page, end=page)

        if len(parts) == 2:
            return cls(
                start=cls._parse_page(parts[0], raw),
                end=cls._parse_page(parts[1], raw),
            )

        raise InvalidPageRangeException(f"No se entiende el rango '{text}'. Se espera '5' o '1-5'.")

    @staticmethod
    def _parse_page(value: str, original: str) -> int:
        stripped = value.strip()

        # A missing half —"1-" while still typing— deserves its own message:
        # reporting that '' is not a valid number reads like a bug.
        if not stripped:
            raise InvalidPageRangeException(f"Falta un número en el rango '{original}'.")

        if not stripped.isdigit():
            raise InvalidPageRangeException(f"'{stripped}' no es un número de página válido en '{original}'.")

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
