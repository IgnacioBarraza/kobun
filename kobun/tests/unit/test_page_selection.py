import pytest

from kobun.domain.pdf.exceptions.invalid_page_range_exception import InvalidPageRangeException
from kobun.domain.pdf.value_objects.page_range import PageRange
from kobun.domain.pdf.value_objects.page_selection import PageSelection


def test_parse_multiple_ranges():
    selection = PageSelection.parse("1-5,10-15")
    assert [str(r) for r in selection] == ["1-5", "10-15"]
    assert selection.total_pages == 11


def test_parse_single_page():
    selection = PageSelection.parse("7")
    assert selection.ranges == (PageRange(start=7, end=7),)
    assert selection.total_pages == 1


def test_parse_mixed_ranges_and_single_pages():
    selection = PageSelection.parse("1-3, 8, 20-22")
    assert str(selection) == "1-3,8,20-22"
    assert selection.to_pages() == [1, 2, 3, 8, 20, 21, 22]


def test_parse_accepts_semicolon_and_whitespace_separators():
    assert PageSelection.parse("1-3; 8") == PageSelection.parse("1-3,8")
    assert PageSelection.parse("1-3 8") == PageSelection.parse("1-3,8")


def test_parse_normalizes_unicode_dashes():
    assert PageSelection.parse("1–5") == PageSelection.parse("1-5")


def test_ranges_are_sorted_regardless_of_input_order():
    selection = PageSelection.parse("30-35,1-5")
    assert str(selection) == "1-5,30-35"
    assert selection.min_page == 1
    assert selection.max_page == 35


def test_overlapping_ranges_are_merged():
    selection = PageSelection.parse("1-5,3-8")
    assert str(selection) == "1-8"
    assert selection.total_pages == 8


def test_contiguous_ranges_are_merged():
    selection = PageSelection.parse("1-5,6-10")
    assert str(selection) == "1-10"


def test_disjoint_ranges_are_not_merged():
    selection = PageSelection.parse("1-5,7-10")
    assert len(selection) == 2


def test_equality_is_based_on_canonical_form():
    assert PageSelection.parse("1-5,3-8") == PageSelection.parse("1-8")
    assert PageSelection.parse("1-5,10") != PageSelection.parse("1-5")


def test_to_pages_has_no_duplicates_when_ranges_overlap():
    pages = PageSelection.parse("1-5,3-8").to_pages()
    assert pages == list(range(1, 9))
    assert len(pages) == len(set(pages))


def test_is_contiguous_flag():
    assert PageSelection.parse("1-10").is_contiguous is True
    assert PageSelection.parse("1-10,20").is_contiguous is False


def test_parse_error_on_empty_text():
    with pytest.raises(InvalidPageRangeException):
        PageSelection.parse("   ")


def test_parse_error_on_non_numeric_page():
    with pytest.raises(InvalidPageRangeException, match="no es un número de página"):
        PageSelection.parse("1-5,abc")


def test_parse_error_on_malformed_range():
    with pytest.raises(InvalidPageRangeException, match="No se entiende"):
        PageSelection.parse("1-2-3")


def test_parse_error_on_inverted_range():
    with pytest.raises(InvalidPageRangeException, match="está al revés"):
        PageSelection.parse("10-5")


def test_parse_error_on_zero_page():
    with pytest.raises(InvalidPageRangeException):
        PageSelection.parse("0-5")


def test_empty_selection_is_rejected():
    with pytest.raises(InvalidPageRangeException, match="al menos un rango"):
        PageSelection(ranges=())
