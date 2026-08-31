"""
The rules that decide which part of a page is a figure.

This is where the "extract the images even when there are none stored" feature
is either useful or noise, so it is tested against the shapes a real page holds:
a border, a rule, a body paragraph, a chart with axis labels, a framed photo.
"""
from kobun.domain.pdf.services import figure_rules
from kobun.domain.pdf.services.figure_rules import (
    FIGURE_PADDING,
    MAX_FIGURE_FRACTION,
    MIN_FIGURE_SIDE,
)
from kobun.domain.pdf.value_objects.rectangle import Rectangle

PAGE = Rectangle(0, 0, 595, 842)

PAGE_BORDER = Rectangle(30, 30, 565, 812)
HORIZONTAL_RULE = Rectangle(72, 95, 520, 95)
BODY_PARAGRAPH = Rectangle(72, 119, 242, 133)
CHART = Rectangle(85, 150, 300, 300)
AXIS_LABELS = [
    Rectangle(98, 303, 110, 316),
    Rectangle(148, 303, 160, 316),
    Rectangle(198, 303, 210, 316),
]


# =========================
# Muebles de la página
# =========================

def test_a_page_border_is_furniture():
    """
    Left in, it merges with everything it encloses and the whole page comes back
    as one figure — which is exactly what the user rejected.
    """
    assert figure_rules.is_page_furniture(PAGE_BORDER, PAGE) is True


def test_a_chart_is_not_furniture():
    assert figure_rules.is_page_furniture(CHART, PAGE) is False


def test_a_full_bleed_background_is_furniture():
    assert figure_rules.is_page_furniture(PAGE, PAGE) is True


def test_furniture_is_dropped_before_grouping():
    kept = figure_rules.usable_drawings([PAGE_BORDER, CHART, HORIZONTAL_RULE], PAGE)

    assert PAGE_BORDER not in kept
    assert CHART in kept


def test_a_rule_survives_the_furniture_filter():
    """
    It is not furniture —it is small— and it is up to the grouping and the
    candidate filter to discard it. Dropping it here would also drop the axis
    lines that belong to a chart.
    """
    assert figure_rules.usable_drawings([HORIZONTAL_RULE], PAGE) == [HORIZONTAL_RULE]


# =========================
# Qué es una figura
# =========================

def test_a_chart_is_a_figure():
    assert figure_rules.is_figure_candidate(CHART, PAGE) is True


def test_a_rule_is_not_a_figure():
    assert figure_rules.is_figure_candidate(HORIZONTAL_RULE, PAGE) is False


def test_something_too_small_is_not_a_figure():
    """A bullet, an axis tick, a fragment of a border."""
    tiny = Rectangle(100, 100, 100 + MIN_FIGURE_SIDE - 1, 140)

    assert figure_rules.is_figure_candidate(tiny, PAGE) is False


def test_a_region_exactly_at_the_minimum_side_is_a_figure():
    exact = Rectangle(100, 100, 100 + MIN_FIGURE_SIDE, 100 + MIN_FIGURE_SIDE)

    assert figure_rules.is_figure_candidate(exact, PAGE) is True


def test_a_region_that_is_really_the_page_is_not_a_figure():
    assert figure_rules.is_figure_candidate(Rectangle(5, 5, 590, 837), PAGE) is False


def test_the_upper_bound_is_inclusive():
    side = (MAX_FIGURE_FRACTION * PAGE.area) ** 0.5
    at_limit = Rectangle(0, 0, side, side)

    assert figure_rules.is_figure_candidate(at_limit, PAGE) is True


# =========================
# Rótulos
# =========================

def test_the_crop_is_padded_so_the_figure_is_not_clipped():
    region = figure_rules.with_labels(CHART, [], PAGE)

    assert region.x0 == CHART.x0 - FIGURE_PADDING
    assert region.y0 == CHART.y0 - FIGURE_PADDING


def test_axis_labels_are_brought_into_the_crop():
    """
    A chart whose labels are cut off is a chart nobody can read, and labels are
    text and therefore outside the drawing's bounds.
    """
    region = figure_rules.with_labels(CHART, AXIS_LABELS, PAGE)

    assert region.y1 >= AXIS_LABELS[0].y1


def test_the_body_paragraph_is_left_out():
    region = figure_rules.with_labels(CHART, [BODY_PARAGRAPH], PAGE)

    assert region.y0 > BODY_PARAGRAPH.y1


def test_a_word_barely_touching_the_margin_is_not_absorbed():
    grazing = Rectangle(CHART.x0, CHART.y1 + FIGURE_PADDING - 1, CHART.x0 + 40, CHART.y1 + 60)

    region = figure_rules.with_labels(CHART, [grazing], PAGE)

    assert region.y1 < grazing.y1


def test_a_stray_word_cannot_stretch_the_crop_across_the_page():
    """
    The growth cap: a word inside the margin should nudge the crop, not redraw
    it.
    """
    far = Rectangle(CHART.x0, CHART.y1 + 2, 560, CHART.y1 + 8)

    region = figure_rules.with_labels(CHART, [far], PAGE)
    padded = CHART.padded(FIGURE_PADDING).clipped_to(PAGE)

    assert region == padded


def test_the_crop_never_sticks_out_of_the_page():
    corner = Rectangle(2, 2, 120, 120)

    region = figure_rules.with_labels(corner, [], PAGE)

    assert region.x0 >= PAGE.x0
    assert region.y0 >= PAGE.y0


def test_labels_do_not_push_the_crop_off_the_page():
    edge = Rectangle(500, 780, 590, 838)
    label = Rectangle(560, 835, 594, 841)

    region = figure_rules.with_labels(edge, [label], PAGE)

    assert region.x1 <= PAGE.x1
    assert region.y1 <= PAGE.y1


# =========================
# Fotos enmarcadas
# =========================

def test_a_frame_drawn_around_a_photo_is_not_extracted_twice():
    """
    The stored bytes win: cropping the frame would hand back a rendered copy of a
    picture already being extracted at full quality.
    """
    photo = Rectangle(72, 200, 272, 350)
    frame = Rectangle(70, 198, 274, 352)

    assert figure_rules.drops_duplicate_of_image(frame, [photo]) is True


def test_a_chart_next_to_a_photo_is_still_extracted():
    photo = Rectangle(350, 200, 550, 350)

    assert figure_rules.drops_duplicate_of_image(CHART, [photo]) is False


def test_a_page_with_no_stored_images_drops_nothing():
    assert figure_rules.drops_duplicate_of_image(CHART, []) is False


# =========================
# Fusión
# =========================

def test_regions_that_overlap_become_one():
    """
    Grouping happens before padding, so two parts of one figure can end up as
    separate regions that overlap once the margin is added. Two crops of the same
    figure, each missing half, is worse than one.
    """
    merged = figure_rules.merge_overlapping(
        [Rectangle(0, 0, 100, 100), Rectangle(80, 80, 180, 180)]
    )

    assert merged == [Rectangle(0, 0, 180, 180)]


def test_separate_figures_stay_separate():
    merged = figure_rules.merge_overlapping(
        [Rectangle(0, 0, 100, 100), Rectangle(300, 300, 400, 400)]
    )

    assert len(merged) == 2


def test_a_chain_of_overlaps_collapses_completely():
    """
    A and C do not touch, but both touch B, so all three are one figure. A single
    pass would leave two.
    """
    merged = figure_rules.merge_overlapping(
        [Rectangle(0, 0, 100, 100), Rectangle(90, 0, 190, 100), Rectangle(180, 0, 280, 100)]
    )

    assert merged == [Rectangle(0, 0, 280, 100)]


def test_merged_regions_come_back_in_reading_order():
    merged = figure_rules.merge_overlapping(
        [Rectangle(0, 500, 100, 600), Rectangle(0, 100, 100, 200), Rectangle(300, 100, 400, 200)]
    )

    assert [r.y0 for r in merged] == [100, 100, 500]
    assert [r.x0 for r in merged[:2]] == [0, 300]


def test_merging_nothing_gives_nothing():
    assert figure_rules.merge_overlapping([]) == []


def test_merging_one_region_leaves_it_alone():
    assert figure_rules.merge_overlapping([CHART]) == [CHART]
