from pathlib import Path
from typing import List, Optional

import pytest

from kobun.application.dto.page_preview import PagePreview
from kobun.application.interfaces.pdf_page_renderer import PdfPageRenderer
from kobun.application.interfaces.pdf_repository import PdfRepository
from kobun.application.use_cases.render_page_preview_use_case import (
    DEFAULT_PREVIEW_WIDTH,
    MAX_PREVIEW_WIDTH,
    MIN_PREVIEW_WIDTH,
    RenderPagePreviewUseCase,
)
from kobun.domain.pdf.entities.pdf_document import PdfDocument, PdfProcessingStatus
from kobun.domain.pdf.exceptions.invalid_extraction_exception import InvalidExtractionException
from kobun.domain.pdf.exceptions.invalid_page_range_exception import InvalidPageRangeException
from kobun.domain.pdf.exceptions.invalid_pdf_exception import InvalidPdfException
from kobun.domain.pdf.value_objects.page_selection import PageSelection


class FakePageRenderer(PdfPageRenderer):
    """Records what it was asked for; the rendering itself is PyMuPDF's business."""

    def __init__(self, fail: bool = False):
        self.calls: List[tuple] = []
        self._fail = fail

    def render_page(self, document, page_number: int, target_width: int) -> PagePreview:
        if self._fail:
            raise RuntimeError("engine exploded")

        self.calls.append((document.filename, page_number, target_width))

        return PagePreview(
            page_number=page_number,
            data=b"\x89PNG fake",
            width=target_width,
            height=int(target_width * 1.414),
        )


class UnusedRepository(PdfRepository):
    """The preview works on an already loaded document, so nothing is re-opened."""

    def __init__(self):
        self.opened: Optional[Path] = None

    def open_document(self, file_path: Path) -> PdfDocument:
        self.opened = file_path
        raise AssertionError("El preview no debe reabrir el documento")

    def close_document(self, document) -> None: ...

    def get_page_count(self, document) -> int: ...

    def extract_metadata(self, document): ...

    def extract_text(self, document, page_number: int) -> str: ...

    def split_single_page(self, src_doc, output_doc, page_index): ...

    def split_page_range(self, src_doc, output_doc, page_range): ...

    def split_page_selection(self, src_doc, output_doc, selection, metadata=None): ...

    def merge_pdfs(self, first_doc, second_doc, output_doc): ...

    def extract_pages(self, document, pages, output_doc): ...


@pytest.fixture
def scenario(make_pdf_document):
    def _build(page_count: int = 40, fail: bool = False):
        document = make_pdf_document(filename="libro.pdf", page_count=page_count)
        renderer = FakePageRenderer(fail=fail)

        return RenderPagePreviewUseCase(UnusedRepository(), renderer), renderer, document

    return _build


# =========================
# Camino feliz
# =========================

def test_a_page_is_rendered_at_the_requested_width(scenario):
    use_case, renderer, document = scenario()

    preview = use_case.execute(document, 7, target_width=300)

    assert preview.page_number == 7
    assert preview.width == 300
    assert renderer.calls == [("libro.pdf", 7, 300)]


def test_the_default_width_is_used_when_none_is_given(scenario):
    use_case, renderer, document = scenario()

    use_case.execute(document, 1)

    assert renderer.calls[0][2] == DEFAULT_PREVIEW_WIDTH


def test_the_first_and_last_pages_are_both_valid(scenario):
    use_case, _, document = scenario(page_count=40)

    assert use_case.execute(document, 1).page_number == 1
    assert use_case.execute(document, 40).page_number == 40


def test_a_preview_leaves_the_document_untouched(scenario):
    """
    It is not an export: nothing is marked as processing, and re-previewing the
    same page any number of times has to stay possible.
    """
    use_case, _, document = scenario()

    for page in (1, 2, 1, 2):
        use_case.execute(document, page)

    assert document.status == PdfProcessingStatus.UPLOADED


def test_the_document_is_not_reopened(scenario):
    """
    The preview works on what is already loaded, so looking at a page costs no
    metadata read and no checksum. UnusedRepository fails loudly if it does.
    """
    use_case, _, document = scenario()

    use_case.execute(document, 3)


# =========================
# Límites de página
# =========================

def test_a_page_past_the_last_one_is_rejected(scenario):
    use_case, renderer, document = scenario(page_count=12)

    with pytest.raises(InvalidPageRangeException, match="no existe"):
        use_case.execute(document, 13)

    assert renderer.calls == [], "No debe renderizar lo que no existe"


def test_page_zero_and_negatives_are_rejected(scenario):
    use_case, _, document = scenario()

    for page in (0, -1):
        with pytest.raises(InvalidPageRangeException):
            use_case.execute(document, page)


@pytest.mark.parametrize("page", ["7", 7.5, None, True])
def test_a_page_that_is_not_a_whole_number_is_rejected(scenario, page):
    use_case, _, document = scenario()

    with pytest.raises(InvalidPageRangeException, match="entero"):
        use_case.execute(document, page)


def test_a_document_whose_file_is_gone_is_rejected(scenario):
    use_case, _, document = scenario()
    document.storage_path.unlink()

    with pytest.raises(InvalidPdfException):
        use_case.execute(document, 1)


# =========================
# Límites de ancho
# =========================

def test_the_usable_widths_are_accepted(scenario):
    use_case, _, document = scenario()

    for width in (MIN_PREVIEW_WIDTH, DEFAULT_PREVIEW_WIDTH, MAX_PREVIEW_WIDTH):
        assert use_case.execute(document, 1, target_width=width).width == width


@pytest.mark.parametrize(
    "width", [0, -100, MIN_PREVIEW_WIDTH - 1, MAX_PREVIEW_WIDTH + 1]
)
def test_a_width_out_of_range_is_rejected(scenario, width):
    use_case, _, document = scenario()

    with pytest.raises(InvalidExtractionException, match="ancho"):
        use_case.execute(document, 1, target_width=width)


@pytest.mark.parametrize("width", ["300", 300.5, None, True])
def test_a_width_that_is_not_a_whole_number_is_rejected(scenario, width):
    use_case, _, document = scenario()

    with pytest.raises(InvalidExtractionException, match="entero"):
        use_case.execute(document, 1, target_width=width)


def test_the_page_is_validated_before_the_width(scenario):
    """
    Both wrong: the page is the user's doing and the width is the screen's, so
    the message that surfaces should be about the page.
    """
    use_case, _, document = scenario(page_count=5)

    with pytest.raises(InvalidPageRangeException):
        use_case.execute(document, 99, target_width=5000)


# =========================
# Qué página mostrar
# =========================

def test_a_selection_is_previewed_at_its_first_page():
    """
    What the user is checking is whether the chapter starts where they think it
    does.
    """
    assert RenderPagePreviewUseCase.first_page_of(PageSelection.parse("10-15,40")) == 10


def test_the_first_page_is_the_lowest_and_not_the_one_typed_first():
    """The domain sorts the ranges, so "40,10-15" starts at ten as well."""
    assert RenderPagePreviewUseCase.first_page_of(PageSelection.parse("40,10-15")) == 10


# =========================
# Fallas del motor
# =========================

def test_an_engine_failure_is_not_swallowed(scenario):
    use_case, _, document = scenario(fail=True)

    with pytest.raises(RuntimeError, match="engine exploded"):
        use_case.execute(document, 1)
