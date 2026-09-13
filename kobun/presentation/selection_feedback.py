"""
Explaining a page selection while it is being typed.

The field used to say "Separá los rangos con comas." and nothing else: an
out-of-bounds range silently disabled the button, and the user was left to guess
whether the problem was the syntax, the page count, or the file. This turns every
keystroke into an answer.

Free of Qt so the wording can be tested without opening a window, and free of
its own parser: the selection is built by the domain, which is the only place
that knows what a valid range is. A message about *why* a range is wrong is the
domain's own, translated nowhere.
"""
from dataclasses import dataclass
from typing import Optional

from kobun.domain.pdf.exceptions.invalid_page_range_exception import InvalidPageRangeException
from kobun.domain.pdf.value_objects.page_selection import PageSelection
from kobun.presentation.formatting import format_page_count

EMPTY_HINT = "Una página, un rango, o varios separados por comas."
"""Says the rule, not more examples: the field's own placeholder already shows
what they look like, and repeating it underneath was saying one thing twice."""


@dataclass(frozen=True)
class SelectionFeedback:
    """
    What to show under the field, and whether it reads as a problem.

    `selection` travels along so the caller does not have to parse the text a
    second time to find out which pages were meant — the preview needs exactly
    that, to jump to the first page of what was asked for.
    """

    message: str

    is_error: bool = False
    """Whether it reads as a problem. A range still being typed is **not** one:
    "1-5" is reached by way of "1-", and turning the line red on the way there
    made every range flash an error at the person writing it."""

    selection: Optional[PageSelection] = None

    @property
    def is_usable(self) -> bool:
        """True when the text describes pages this document actually has."""
        return self.selection is not None and not self.is_error


def describe(raw_text: str, page_count: Optional[int] = None) -> SelectionFeedback:
    """
    :param raw_text: Exactly what is in the field.
    :param page_count: Pages in the loaded document, or None when none is open.
        Without it the syntax can still be checked, but the bounds cannot.
    """
    text = raw_text.strip()
    if not text:
        return SelectionFeedback(EMPTY_HINT)

    try:
        selection = PageSelection.parse(text)
    except InvalidPageRangeException as error:
        # The domain's own message: it already says which part does not parse,
        # and rewording it here would mean maintaining two explanations. Whether
        # it *reads* as a problem is this layer's call, because only the screen
        # knows the range is still being typed.
        return SelectionFeedback(str(error), is_error=not _is_unfinished(text))

    if page_count is not None and selection.max_page > page_count:
        return SelectionFeedback(
            f"La página {selection.max_page} no existe: este PDF llega hasta la {page_count}.",
            is_error=True,
            selection=selection,
        )

    return SelectionFeedback(_summary(text, selection), selection=selection)


def _summary(text: str, selection: PageSelection) -> str:
    """
    "6 páginas", or "8 páginas · se toma 1-8" when the canonical form differs
    from what was typed.

    The second case is worth saying out loud: the domain merges overlapping and
    adjacent ranges, so "3-8,1-5" is eight pages and not thirteen, and "5,5" is
    one page and not two. Reporting only the count would look like a bug.
    """
    count = format_page_count(selection.total_pages)
    canonical = str(selection)

    if _normalized(text) == canonical:
        return count

    return f"{count}: {canonical}"


def _normalized(text: str) -> str:
    """
    The typed text reduced to the shape `str(PageSelection)` produces, so that
    cosmetic differences —spaces, a trailing comma, a semicolon— are not reported
    as if the selection had been rewritten.
    """
    for separator in (";", " ", "\t", "\n"):
        text = text.replace(separator, ",")

    chunks = [chunk.strip() for chunk in text.split(",") if chunk.strip()]

    return ",".join(chunks)
def _is_unfinished(text: str) -> bool:
    """
    Whether the text looks like a range halfway through being typed, rather than
    a wrong one.

    Only the trailing dash: "1-" is what "1-5" passes through, and it is the one
    invalid state a person produces on their way to a valid one. "-5" and "10-2"
    are finished and wrong, and are reported as such.
    """
    return text.rstrip().endswith("-")
