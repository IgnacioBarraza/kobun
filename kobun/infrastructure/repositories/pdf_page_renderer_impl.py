from typing import Optional

from kobun.application.dto.page_preview import PagePreview
from kobun.application.interfaces.pdf_page_renderer import PdfPageRenderer
from kobun.domain.pdf.entities.pdf_document import PdfDocument
from kobun.infrastructure.pdf_engine.pdf_document_opener import PdfDocumentOpener
from kobun.infrastructure.pdf_engine.pdf_engine_adapter import PdfEngineAdapter


class PyMuPdfPageRenderer(PdfPageRenderer):
    """
    PdfPageRenderer implementation over PyMuPDF.

    It shares PdfDocumentOpener with the repository and the asset extractor, so a
    file rejected for splitting is rejected here too, with the same message. The
    document is opened and closed around each render: holding it open between
    previews would keep a handle on a file the user is free to move, and on
    Windows would lock it.
    """

    def __init__(self, engine: PdfEngineAdapter, opener: Optional[PdfDocumentOpener] = None):
        self._engine = engine
        self._opener = opener or PdfDocumentOpener(engine)

    def render_page(
        self,
        document: PdfDocument,
        page_number: int,
        target_width: int,
    ) -> PagePreview:
        source = self._opener.open(document.storage_path)

        try:
            data, width, height = self._engine.render_page_to_width(
                source, page_number, target_width
            )
        finally:
            self._engine.close_document(source)

        return PagePreview(
            page_number=page_number, data=data, width=width, height=height
        )
