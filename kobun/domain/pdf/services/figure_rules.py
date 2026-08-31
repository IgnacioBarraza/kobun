"""
Deciding which part of a page is a figure.

This is the answer to "the PDF has no stored image, but I can see the chart":
a vector drawing is not an image, so the only way to hand one over is to work
out the region it occupies and render just that. Every rule here is geometry
over `Rectangle`, deliberately free of PyMuPDF, because this is the part where
the feature is either useful or noise and it has to be testable exhaustively.

The engine contributes three raw ingredients and no judgement:

- the bounding box of every vector drawing on the page
- the boxes of the words on the page
- the boxes where stored images are placed

What counts as a figure, and what is furniture, is decided here.
"""
from typing import Iterable, List, Sequence

from kobun.domain.pdf.value_objects.rectangle import Rectangle

MAX_FURNITURE_FRACTION = 0.60
"""A single drawing covering more than this much of the page is furniture: a
border, a watermark, a coloured background. Left in, it merges with everything
it encloses and the whole page comes back as one "figure" — which is the exact
outcome the user rejected."""

MIN_FIGURE_SIDE = 24.0
"""Points. Below this on either side there is nothing worth opening: a bullet, a
tick on an axis, a fragment of a rule."""

MAX_FIGURE_FRACTION = 0.80
"""A region past this is not a figure on a page, it is the page."""

FIGURE_PADDING = 12.0
"""Points of margin around a figure.

Two jobs: a figure cropped exactly at its own outline looks clipped, and axis
labels sit just outside the drawing's bounds —a few points below the axis— so
the margin is also what brings them into reach of the rule below."""

LABEL_INSIDE_RATIO = 0.6
"""How much of a word must fall inside the padded region to be considered part
of the figure. Set so axis labels and legends come along while the body
paragraph beside the figure does not."""

MAX_LABEL_GROWTH = 0.35
"""Cap on how much absorbing labels may grow a region, per axis. Without it a
single stray word inside the margin can stretch the crop across the page."""


def is_page_furniture(drawing: Rectangle, page: Rectangle) -> bool:
    """
    Whether a drawing should be ignored before grouping, because it frames or
    fills the page instead of depicting something.
    """
    return drawing.covers_fraction_of(page) > MAX_FURNITURE_FRACTION


def usable_drawings(drawings: Iterable[Rectangle], page: Rectangle) -> List[Rectangle]:
    """The drawings worth grouping into figures."""
    return [drawing for drawing in drawings if not is_page_furniture(drawing, page)]


def is_figure_candidate(region: Rectangle, page: Rectangle) -> bool:
    """
    Whether a grouped region is worth handing over as a figure.

    Rejects three things: what has no surface (a rule), what is too small to be
    a figure, and what is so large it is really the page.
    """
    if region.is_empty:
        return False

    if region.shortest_side < MIN_FIGURE_SIDE:
        return False

    return region.covers_fraction_of(page) <= MAX_FIGURE_FRACTION


def with_labels(region: Rectangle, words: Sequence[Rectangle], page: Rectangle) -> Rectangle:
    """
    The region to crop: padded, then grown to include the words that mostly fall
    inside that margin, and finally trimmed to the page.

    A chart whose axis labels are cut off is a chart nobody can read, and the
    labels are text and therefore outside the drawing's bounds. Absorbing only
    what is *mostly* inside the margin is what separates "Q1 Q2 Q3 Q4" from the
    paragraph next to the figure.
    """
    padded = region.padded(FIGURE_PADDING).clipped_to(page)
    grown = padded

    for word in words:
        if padded.area_fraction_of(word) >= LABEL_INSIDE_RATIO:
            grown = grown.union(word)

    grown = grown.clipped_to(page)

    return padded if _grew_too_much(padded, grown) else grown


def _grew_too_much(padded: Rectangle, grown: Rectangle) -> bool:
    """
    A word inside the margin should nudge the crop, not redraw it. Past the cap
    the padded region is kept as it was, which is still a usable figure.
    """
    for before, after in ((padded.width, grown.width), (padded.height, grown.height)):
        if before <= 0:
            continue
        if (after - before) / before > MAX_LABEL_GROWTH:
            return True

    return False


def drops_duplicate_of_image(region: Rectangle, image_boxes: Sequence[Rectangle]) -> bool:
    """
    Whether a region is really a stored image that happens to be framed.

    A photo with a drawn border produces a drawing around it, and cropping that
    would hand back a rendered copy of a picture already being extracted at full
    quality. The stored bytes win.
    """
    return any(region.area_fraction_of(box) >= LABEL_INSIDE_RATIO for box in image_boxes)


def merge_overlapping(regions: Sequence[Rectangle]) -> List[Rectangle]:
    """
    Fuses regions that touch once padded, repeatedly, until none do.

    Grouping happens before padding, so two parts of one figure can end up as
    separate regions that overlap after the margin is added. Handing over two
    crops of the same figure, each missing half of it, is worse than one.
    """
    merged: List[Rectangle] = list(regions)
    changed = True

    while changed:
        changed = False
        result: List[Rectangle] = []

        for candidate in merged:
            for index, existing in enumerate(result):
                if existing.overlaps(candidate):
                    result[index] = existing.union(candidate)
                    changed = True
                    break
            else:
                result.append(candidate)

        merged = result

    return sorted(merged, key=lambda r: (r.y0, r.x0))
