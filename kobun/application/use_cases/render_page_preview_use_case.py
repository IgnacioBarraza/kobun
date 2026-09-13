from kobun.application.dto.page_preview import PagePreview
from kobun.application.interfaces.pdf_page_renderer import PdfPageRenderer
from kobun.application.interfaces.pdf_repository import PdfRepository
from kobun.domain.pdf.entities.pdf_document import PdfDocument
from kobun.domain.pdf.exceptions.invalid_extraction_exception import InvalidExtractionException
from kobun.domain.pdf.services import selection_rules
from kobun.domain.pdf.value_objects.page_selection import PageSelection

DEFAULT_PREVIEW_WIDTH = 420
"""Pixels. Wide enough that an A4 page's headings are readable and its layout
recognisable, small enough to render in a few milliseconds and to scale down
crisply to whatever space the panel has."""

MIN_PREVIEW_WIDTH = 40
MAX_PREVIEW_WIDTH = 2000
"""A preview is looked at, not exported. Past this the render stops being a
thumbnail and starts costing what a real page render costs, which is what the
extraction screen is for."""


class RenderPagePreviewUseCase:
    """
    Renders one page of the loaded document so it can be looked at before
    committing to an export.

    Deliberately not part of the split: the preview answers a question the user
    asks *instead* of pressing the button, and nothing it does touches disk. It
    re-opens the source on each call, like every other operation here, so a file
    that was moved or replaced in the meantime fails as a preview rather than as
    a corrupt export.
    """

    def __init__(self, pdf_repository: PdfRepository, page_renderer: PdfPageRenderer):
        self._pdf_repository = pdf_repository
        self._page_renderer = page_renderer

    def execute(
        self,
        document: PdfDocument,
        page_number: int,
        target_width: int = DEFAULT_PREVIEW_WIDTH,
    ) -> PagePreview:
        """
        :param document: The already loaded document, so a preview costs no
            metadata read or checksum.
        :param page_number: 1-based page to paint.
        :param target_width: Width in pixels.
        :raises InvalidPageRangeException: If the page is outside the document.
        :raises InvalidExtractionException: If the width is unusable.
        """
        selection_rules.validate_page(document, page_number)
        self._validate_width(target_width)

        return self._page_renderer.render_page(document, page_number, target_width)

    @staticmethod
    def first_page_of(selection: PageSelection) -> int:
        """
        Which page a selection should be previewed at.

        A rule and not an incidental choice: the interesting page of "10-15,40"
        is the tenth, because what the user is checking is whether the chapter
        starts where they think it does.
        """
        return selection.min_page

    @staticmethod
    def _validate_width(target_width: int) -> None:
        if not isinstance(target_width, int) or isinstance(target_width, bool):
            raise InvalidExtractionException(
                f"El ancho de la vista previa tiene que ser entero. Se recibió: {target_width!r}"
            )

        if target_width < MIN_PREVIEW_WIDTH or target_width > MAX_PREVIEW_WIDTH:
            raise InvalidExtractionException(
                f"El ancho de la vista previa debe estar entre {MIN_PREVIEW_WIDTH} y "
                f"{MAX_PREVIEW_WIDTH} píxeles. Se pidió: {target_width}."
            )
