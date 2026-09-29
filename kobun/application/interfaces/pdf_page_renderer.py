from abc import ABC, abstractmethod

from kobun.application.dto.page_preview import PagePreview
from kobun.domain.pdf.entities.pdf_document import PdfDocument


class PdfPageRenderer(ABC):
    """
    Painting a single page small, for the preview.

    Kept apart from PdfAssetExtractor even though both rasterise pages: that one
    streams a selection at a chosen resolution to be written to disk, this one
    answers "what does page 7 look like" at a size measured in pixels. Sizing a
    thumbnail in dpi would mean the caller computing a resolution from a widget's
    width, which is the wrong way round.
    """

    @abstractmethod
    def render_page(
        self,
        document: PdfDocument,
        page_number: int,
        target_width: int,
    ) -> PagePreview:
        """
        :param page_number: 1-based page.
        :param target_width: Width in pixels to render at. The height follows
            from the page's own proportions, which are never distorted: a
            landscape page comes back wide.
        """
        pass
