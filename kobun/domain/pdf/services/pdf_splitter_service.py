from pathlib import PurePath

from kobun.domain.pdf.entities.pdf_document import PdfDocument
from kobun.domain.pdf.services import selection_rules
from kobun.domain.pdf.services.filename_rules import (
    FALLBACK_STEM,
    PDF_SUFFIX,
    sanitize_filename,
    sanitized_stem,
)
from kobun.domain.pdf.value_objects.page_selection import PageSelection
from kobun.domain.pdf.value_objects.pdf_metadata import PdfMetadata

CREATOR_NAME = "Kobun PDF Utility"

# Re-exported: several modules import PDF_SUFFIX and FALLBACK_STEM from here,
# which was their home before the naming rules were shared with the extractor.
__all__ = [
    "CREATOR_NAME",
    "FALLBACK_STEM",
    "PDF_SUFFIX",
    "PdfSplitterService",
]


class PdfSplitterService:
    """
    Domain Service holding the business rules of splitting.

    It knows neither PyMuPDF nor the filesystem beyond checking that the
    document exists: it only decides which operations are legitimate and what
    the resulting metadata should look like.
    """

    def validate_document_for_processing(self, document: PdfDocument) -> None:
        """
        Checks the document is in a state that allows manipulation.
        """
        selection_rules.validate_document_for_processing(document)

    def validate_selection(self, document: PdfDocument, selection: PageSelection) -> None:
        """
        Ensures every requested page exists within the document.
        """
        selection_rules.validate_selection(document, selection)

    def suggest_output_filename(self, source_doc: PdfDocument, selection: PageSelection) -> str:
        """
        Suggested filename for the result: "book.pdf" + "1-5,10-15" becomes
        "book_1-5_10-15.pdf".

        This is a business rule —how Kobun names its exports— and not a UI
        decision, so it lives in the domain. The UI can offer it as an editable
        default in the save dialog.
        """
        stem = sanitized_stem(source_doc.filename)
        suffix = str(selection).replace(",", "_")

        return f"{stem}_{suffix}{PDF_SUFFIX}"

    @staticmethod
    def _sanitize_filename(value: str) -> str:
        """
        Kept as a thin delegate: the rule now lives in `filename_rules`, shared
        with the asset extractor.
        """
        return sanitize_filename(value)

    def prepare_split_metadata(self, source_doc: PdfDocument, selection: PageSelection) -> PdfMetadata:
        """
        Builds the resulting PDF's metadata by deriving it from the original,
        so the exported file is traceable back to its source.

        The title never carries the extension: it is a document title, not a
        filename. The `subject` does keep the full name, because there what
        matters is being able to identify the source file.
        """
        source_meta = source_doc.metadata
        base = source_meta.title or PurePath(source_doc.filename).stem

        return PdfMetadata(
            title=f"{base} ({selection})",
            author=source_meta.author,
            subject=f"Páginas {selection} extraídas de {source_doc.filename}",
            keywords=source_meta.keywords,
            creator=CREATOR_NAME,
            producer=source_meta.producer,
        )
