"""
What the field says while a selection is being typed.

Every message here is read by a person mid-keystroke, so the wording is worth a
test: this is the only thing that explains why a range cannot be used.
"""
import pytest

from kobun.presentation import selection_feedback
from kobun.presentation.selection_feedback import EMPTY_HINT, describe


# =========================
# Campo vacío
# =========================

def test_an_empty_field_shows_the_hint():
    feedback = describe("", page_count=12)

    assert feedback.message == EMPTY_HINT
    assert feedback.is_error is False
    assert feedback.selection is None
    assert feedback.is_usable is False


def test_only_whitespace_counts_as_empty():
    assert describe("   ", page_count=12).message == EMPTY_HINT


# =========================
# Cuánto se va a extraer
# =========================

def test_a_single_page_is_counted_in_the_singular():
    assert describe("7", page_count=12).message == "1 página"


def test_a_range_reports_its_page_count():
    assert describe("1-5", page_count=12).message == "5 páginas"


def test_discontinuous_ranges_are_added_up():
    assert describe("1-5,10", page_count=12).message == "6 páginas"


def test_a_valid_selection_travels_with_the_message():
    """
    So the caller does not parse the text a second time: the preview needs the
    selection to jump to its first page.
    """
    feedback = describe("4-9", page_count=12)

    assert feedback.is_usable is True
    assert str(feedback.selection) == "4-9"


# =========================
# Cuando el dominio reescribe la selección
# =========================

def test_merged_ranges_are_reported_as_merged():
    """
    The domain merges overlapping ranges, so "3-8,1-5" is eight pages and not
    thirteen. Reporting only the count would look like a bug.
    """
    assert describe("3-8,1-5", page_count=12).message == "8 páginas: 1-8"


def test_a_repeated_page_is_counted_once():
    assert describe("5,5", page_count=12).message == "1 página: 5"


def test_adjacent_ranges_are_reported_as_one():
    assert describe("1-3,4-6", page_count=12).message == "6 páginas: 1-6"


def test_ranges_out_of_order_are_reported_sorted():
    assert describe("10,2", page_count=12).message == "2 páginas: 2,10"


@pytest.mark.parametrize("text", ["1-5, 10", "1-5,10,", "1-5;10", "1-5 10", " 1-5,10 "])
def test_cosmetic_differences_are_not_reported_as_a_rewrite(text):
    """
    A space, a trailing comma or a semicolon changes nothing about which pages
    were chosen, and spelling the selection back out for input that already said
    it would be noise.
    """
    assert describe(text, page_count=12).message == "6 páginas"


# =========================
# Fuera de los límites del PDF
# =========================

def test_a_range_past_the_last_page_is_an_error():
    feedback = describe("1-5,20", page_count=12)

    assert feedback.is_error is True
    assert feedback.is_usable is False
    assert feedback.message == "La página 20 no existe: este PDF llega hasta la 12."


def test_the_last_page_is_within_bounds():
    assert describe("12", page_count=12).is_usable is True


def test_the_selection_is_still_reported_when_out_of_bounds():
    """
    It parsed fine; only the document is too short. The caller may still want to
    know what was meant.
    """
    assert str(describe("20", page_count=12).selection) == "20"


def test_without_a_document_the_bounds_are_not_checked():
    """
    The syntax can still be explained before a PDF is open, which is what the
    field does while the user is looking for one.
    """
    feedback = describe("500-600", page_count=None)

    assert feedback.is_error is False
    assert feedback.message == "101 páginas"


# =========================
# Errores de sintaxis
# =========================

def test_letters_are_rejected_with_the_offending_text():
    feedback = describe("abc", page_count=12)

    assert feedback.is_error is True
    assert "abc" in feedback.message


def test_a_half_typed_range_says_which_number_is_missing():
    """What the field shows constantly, since "1-5" passes through "1-"."""
    assert describe("1-", page_count=12).message == (
        "Falta la página en la que termina el rango."
    )


def test_a_range_missing_its_start_says_so():
    """The other half names itself too, instead of one sentence for both ends."""
    assert describe("-5", page_count=12).message == (
        "Falta la página en la que empieza el rango."
    )


def test_a_backwards_range_offers_the_fix():
    """The fix is always the same two numbers the other way round."""
    assert describe("10-2", page_count=12).message == "10-2 está al revés: escribí 2-10."


def test_page_zero_is_rejected():
    assert describe("0", page_count=12).is_error is True


def test_page_zero_does_not_echo_an_internal_range():
    """
    A lone "0" becomes the range 0-0 inside the domain, and answering "0-0" to
    someone who typed one character shows them a shape they never wrote.
    """
    assert describe("0", page_count=12).message == "Las páginas se cuentan desde 1."


def test_a_syntax_error_carries_no_selection():
    feedback = describe("1-x", page_count=12)

    assert feedback.selection is None
    assert feedback.is_usable is False


def test_the_message_is_the_domain_s_own():
    """
    Not reworded here: the domain already says which part does not parse, and
    keeping a second copy of that explanation is how the two drift apart.
    """
    from kobun.domain.pdf.exceptions.invalid_page_range_exception import (
        InvalidPageRangeException,
    )
    from kobun.domain.pdf.value_objects.page_selection import PageSelection

    try:
        PageSelection.parse("9-x")
        raise AssertionError("debería haber fallado")
    except InvalidPageRangeException as error:
        assert describe("9-x", page_count=12).message == str(error)


def test_every_message_is_in_spanish():
    """
    The domain's range messages used to be English while the rest of the app was
    Spanish, and they reach the user through this field.
    """
    english = ("Invalid", "cannot", "Expected", "empty", "page number '")

    for text in ("abc", "1-", "10-2", "0", "1--5", "1-5,20"):
        message = describe(text, page_count=12).message
        assert not any(word in message for word in english), message
