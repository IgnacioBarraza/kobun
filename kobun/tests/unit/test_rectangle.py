import pytest

from kobun.domain.pdf.exceptions.invalid_extraction_exception import InvalidExtractionException
from kobun.domain.pdf.value_objects.rectangle import Rectangle


def test_a_rectangle_reports_its_measures():
    rect = Rectangle(10, 20, 110, 70)

    assert rect.width == 100
    assert rect.height == 50
    assert rect.area == 5000
    assert rect.shortest_side == 50


def test_corners_given_in_any_order_produce_the_same_rectangle():
    """
    A drawing's box can arrive with the corners the other way round, and every
    ratio built on an inverted rectangle would be wrong.
    """
    assert Rectangle(110, 70, 10, 20) == Rectangle(10, 20, 110, 70)


def test_normalising_does_not_collapse_the_rectangle():
    """
    Regression: assigning x0 before reading it again made max() see the value it
    had just replaced, turning a corner-first rectangle into a point.
    """
    rect = Rectangle(110, 60, 10, 10)

    assert (rect.x0, rect.y0, rect.x1, rect.y1) == (10.0, 10.0, 110.0, 60.0)


def test_coordinates_are_kept_as_floats():
    rect = Rectangle(1, 2, 3, 4)

    assert isinstance(rect.x0, float)


@pytest.mark.parametrize("bad", ["10", None, object()])
def test_a_coordinate_that_is_not_a_number_is_rejected(bad):
    with pytest.raises(InvalidExtractionException, match="Coordenada inválida"):
        Rectangle(bad, 0, 10, 10)


def test_a_boolean_is_not_accepted_as_a_coordinate():
    """It is an int for Python, and finding one here means something is miswired."""
    with pytest.raises(InvalidExtractionException):
        Rectangle(True, 0, 10, 10)


# =========================
# Vacíos
# =========================

def test_a_horizontal_rule_is_empty():
    """A rule has no surface, so nothing can be cropped out of it."""
    assert Rectangle(72, 95, 520, 95).is_empty is True


def test_a_vertical_rule_is_empty():
    assert Rectangle(72, 95, 72, 500).is_empty is True


def test_a_real_rectangle_is_not_empty():
    assert Rectangle(0, 0, 10, 10).is_empty is False


# =========================
# Operaciones
# =========================

def test_padding_grows_every_side():
    assert Rectangle(10, 10, 110, 60).padded(5) == Rectangle(5, 5, 115, 65)


def test_padding_by_zero_changes_nothing():
    rect = Rectangle(10, 10, 110, 60)

    assert rect.padded(0) == rect


def test_union_covers_both():
    assert Rectangle(0, 0, 50, 50).union(Rectangle(100, 100, 150, 150)) == Rectangle(
        0, 0, 150, 150
    )


def test_intersection_is_the_shared_surface():
    assert Rectangle(0, 0, 100, 100).intersection(Rectangle(50, 50, 150, 150)) == Rectangle(
        50, 50, 100, 100
    )


def test_the_intersection_of_disjoint_rectangles_is_empty():
    """
    Collapsed to a zero rectangle rather than left inverted: an inverted one
    reports a positive area and every ratio built on it lies.
    """
    result = Rectangle(0, 0, 10, 10).intersection(Rectangle(100, 100, 110, 110))

    assert result.is_empty is True
    assert result.area == 0


def test_rectangles_touching_at_an_edge_do_not_overlap():
    assert Rectangle(0, 0, 50, 50).overlaps(Rectangle(50, 0, 100, 50)) is False


def test_overlapping_rectangles_report_it():
    assert Rectangle(0, 0, 50, 50).overlaps(Rectangle(40, 40, 90, 90)) is True


def test_clipping_trims_what_sticks_out_of_the_page():
    page = Rectangle(0, 0, 595, 842)

    assert Rectangle(-20, -20, 100, 100).clipped_to(page) == Rectangle(0, 0, 100, 100)


def test_clipping_leaves_what_is_already_inside():
    page = Rectangle(0, 0, 595, 842)
    inside = Rectangle(50, 50, 100, 100)

    assert inside.clipped_to(page) == inside


# =========================
# Proporciones
# =========================

def test_area_fraction_reports_how_much_of_the_other_is_inside():
    half = Rectangle(0, 0, 50, 100)

    assert half.area_fraction_of(Rectangle(0, 0, 100, 100)) == pytest.approx(0.5)


def test_area_fraction_of_something_fully_inside_is_one():
    assert Rectangle(0, 0, 100, 100).area_fraction_of(Rectangle(10, 10, 20, 20)) == 1.0


def test_area_fraction_of_something_outside_is_zero():
    assert Rectangle(0, 0, 10, 10).area_fraction_of(Rectangle(500, 500, 600, 600)) == 0.0


def test_area_fraction_of_a_degenerate_rectangle_is_zero():
    """A rule has no area, so no meaningful fraction of it is inside anything."""
    assert Rectangle(0, 0, 100, 100).area_fraction_of(Rectangle(10, 10, 90, 10)) == 0.0


def test_covers_fraction_compares_the_two_areas():
    page = Rectangle(0, 0, 100, 100)

    assert Rectangle(0, 0, 50, 50).covers_fraction_of(page) == pytest.approx(0.25)


def test_covers_fraction_of_a_degenerate_reference_is_zero():
    assert Rectangle(0, 0, 10, 10).covers_fraction_of(Rectangle(0, 0, 0, 0)) == 0.0
