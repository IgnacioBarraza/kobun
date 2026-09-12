import pytest

from kobun.domain.pdf.exceptions.invalid_page_range_exception import InvalidPageRangeException
from kobun.domain.pdf.value_objects.page_range import PageRange


def test_page_range_creation_success():
    p_range = PageRange(start=1, end=10)
    assert p_range.start == 1
    assert p_range.end == 10


def test_page_range_to_range_conversion():
    p_range = PageRange(start=1, end=3)
    assert list(p_range.to_range()) == [1, 2, 3]  #


def test_page_range_error_when_start_is_greater_than_end():
    with pytest.raises(InvalidPageRangeException, match="no puede ser mayor"):
        PageRange(start=10, end=5)


def test_page_range_error_with_negative_values():
    with pytest.raises(InvalidPageRangeException):
        PageRange(start=0, end=10)


def test_page_range_string_representation():
    p_range = PageRange(start=5, end=15)
    assert str(p_range) == "5-15"


def test_single_page_range_string_representation():
    assert str(PageRange(start=7, end=7)) == "7"


def test_parse_range():
    assert PageRange.parse("1-5") == PageRange(start=1, end=5)


def test_parse_single_page():
    assert PageRange.parse("7") == PageRange(start=7, end=7)


def test_parse_ignores_surrounding_whitespace():
    assert PageRange.parse("  1 - 5 ") == PageRange(start=1, end=5)


def test_parse_error_on_missing_bound():
    """
    A half-typed range gets its own message: saying that '' is not a valid page
    number reads like a bug, and this is what the field shows while the user is
    still typing.
    """
    with pytest.raises(InvalidPageRangeException, match="Falta un número"):
        PageRange.parse("1-")

    with pytest.raises(InvalidPageRangeException, match="Falta un número"):
        PageRange.parse("-5")


def test_parse_error_on_empty_text():
    with pytest.raises(InvalidPageRangeException, match="no puede estar vac"):
        PageRange.parse("  ")


def test_contains():
    p_range = PageRange(start=5, end=10)
    assert p_range.contains(5)
    assert p_range.contains(10)
    assert not p_range.contains(4)
    assert not p_range.contains(11)


def test_merge_contiguous_ranges():
    assert PageRange(start=1, end=5).merge(PageRange(start=6, end=10)) == PageRange(start=1, end=10)


def test_merge_overlapping_ranges():
    assert PageRange(start=1, end=6).merge(PageRange(start=3, end=10)) == PageRange(start=1, end=10)


def test_merge_error_on_disjoint_ranges():
    with pytest.raises(InvalidPageRangeException, match="rangos separados"):
        PageRange(start=1, end=5).merge(PageRange(start=8, end=10))