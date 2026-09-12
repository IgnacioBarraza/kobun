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

EMPTY_HINT = "Separá los rangos con comas: 1-5,10-15,20"


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
        # and rewording it here would mean maintaining two explanations.
        return SelectionFeedback(str(error), is_error=True)

    if page_count is not None and selection.max_page > page_count:
        return SelectionFeedback(
            f"El PDF tiene {page_count} páginas y pediste hasta la {selection.max_page}.",
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

    return f"{count} · se toma {canonical}"


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
