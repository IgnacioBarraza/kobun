"""
When a document and a page selection are workable.

Extracted from PdfSplitterService because the same rule now guards two
operations —splitting and extracting assets— and having the bounds message
written twice is how the two drift apart.
"""
from kobun.domain.pdf.entities.pdf_document import PdfDocument
from kobun.domain.pdf.exceptions.invalid_page_range_exception import InvalidPageRangeException
from kobun.domain.pdf.exceptions.invalid_pdf_exception import InvalidPdfException
from kobun.domain.pdf.value_objects.page_selection import PageSelection


def validate_document_for_processing(document: PdfDocument) -> None:
    """
    Checks the document is in a state that allows manipulation.

    :raises InvalidPdfException: If it has no pages or the file is gone.
    """
    if document.page_count is None or document.page_count <= 0:
        raise InvalidPdfException("El documento no tiene páginas válidas para procesar.")

    if not document.storage_path.exists():
        raise InvalidPdfException(f"El archivo físico no existe en: {document.storage_path}")


def validate_selection(document: PdfDocument, selection: PageSelection) -> None:
    """
    Ensures every requested page exists within the document.

    :raises InvalidPdfException: If the document itself is unusable.
    :raises InvalidPageRangeException: If the selection goes past the last page.
    """
    validate_document_for_processing(document)

    if selection.max_page > document.page_count:
        raise InvalidPageRangeException(
            f"Rango fuera de límites: El PDF tiene {document.page_count} páginas, "
            f"pero se pidió hasta la {selection.max_page}."
        )
