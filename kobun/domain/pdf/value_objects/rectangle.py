from dataclasses import dataclass

from kobun.domain.pdf.exceptions.invalid_extraction_exception import InvalidExtractionException


@dataclass(frozen=True, slots=True)
class Rectangle:
    """
    An axis-aligned rectangle in PDF points, with the origin at the top left.

    It exists so the rules for deciding *which part of a page is a figure* can
    live in the domain and be tested without PyMuPDF. The engine has its own
    rect type; the adapter converts at the boundary, and nothing above it knows
    that type exists.

    Always kept normalised —x0 <= x1, y0 <= y1— so a rectangle built from
    corners in any order behaves the same. An empty rectangle (zero width or
    height) is legal: a horizontal rule is one, and recognising it as
    degenerate is precisely one of the rules.
    """

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        for name, value in (("x0", self.x0), ("y0", self.y0), ("x1", self.x1), ("y1", self.y1)):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise InvalidExtractionException(f"Coordenada inválida en {name}: {value!r}")

        # All four read before any is written: assigning x0 first would make the
        # max() below see the value it had just replaced, collapsing a rectangle
        # given corner-first into a point.
        left, right = min(self.x0, self.x1), max(self.x0, self.x1)
        top, bottom = min(self.y0, self.y1), max(self.y0, self.y1)

        object.__setattr__(self, "x0", float(left))
        object.__setattr__(self, "x1", float(right))
        object.__setattr__(self, "y0", float(top))
        object.__setattr__(self, "y1", float(bottom))

    # =========================
    # Medidas
    # =========================

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def is_empty(self) -> bool:
        """
        True when it encloses no surface: a rule, a hairline, a stray point.
        Nothing can be cropped out of it.
        """
        return self.area <= 0

    @property
    def shortest_side(self) -> float:
        return min(self.width, self.height)

    # =========================
    # Operaciones
    # =========================

    def padded(self, amount: float) -> "Rectangle":
        """
        Grown by `amount` on every side. A figure cropped exactly at its own
        outline looks clipped rather than framed.
        """
        return Rectangle(
            self.x0 - amount, self.y0 - amount, self.x1 + amount, self.y1 + amount
        )

    def union(self, other: "Rectangle") -> "Rectangle":
        return Rectangle(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def intersection(self, other: "Rectangle") -> "Rectangle":
        """
        The shared surface, or an empty rectangle when they do not meet.

        Collapsed to a zero rectangle rather than allowed to come out inverted:
        an inverted rectangle would report a positive area and every ratio built
        on it would lie.
        """
        x0 = max(self.x0, other.x0)
        y0 = max(self.y0, other.y0)
        x1 = min(self.x1, other.x1)
        y1 = min(self.y1, other.y1)

        if x1 <= x0 or y1 <= y0:
            return Rectangle(x0, y0, x0, y0)

        return Rectangle(x0, y0, x1, y1)

    def clipped_to(self, bounds: "Rectangle") -> "Rectangle":
        """Trimmed so it never sticks out of the page."""
        return self.intersection(bounds)

    def overlaps(self, other: "Rectangle") -> bool:
        return not self.intersection(other).is_empty

    def area_fraction_of(self, other: "Rectangle") -> float:
        """
        How much of `other`'s surface this rectangle covers, between 0 and 1.

        Returns 0 for a degenerate `other` instead of dividing by zero: a rule
        has no area, so no meaningful fraction of it can be inside anything.
        """
        if other.is_empty:
            return 0.0

        return self.intersection(other).area / other.area

    def covers_fraction_of(self, other: "Rectangle") -> float:
        """How much of `other` this rectangle takes up, by area."""
        if other.is_empty:
            return 0.0

        return self.area / other.area

    def __str__(self) -> str:
        return f"({self.x0:.1f}, {self.y0:.1f})-({self.x1:.1f}, {self.y1:.1f})"
