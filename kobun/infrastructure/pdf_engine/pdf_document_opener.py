from pathlib import Path

from pymupdf import Document

from kobun.domain.pdf.exceptions.encrypted_pdf_exception import EncryptedPdfException
from kobun.domain.pdf.exceptions.invalid_pdf_exception import InvalidPdfException
from kobun.domain.pdf.exceptions.pdf_not_found_exception import PdfNotFoundException
from kobun.infrastructure.pdf_engine.pdf_engine_adapter import PdfEngineAdapter

_PDF_SUFFIX = ".pdf"


class PdfDocumentOpener:
    """
    The single point where a file becomes an open engine document.

    Extracted from PyMuPdfRepository once the asset extractor needed to open the
    same files under the same rules: an encrypted PDF has to be rejected with
    the same message whether the user asked to split it or to pull its images
    out, and two copies of that decision would have drifted.

    Every engine failure is translated into a domain exception here, so no layer
    above ever sees a PyMuPDF error.
    """

    def __init__(self, engine: PdfEngineAdapter):
        self._engine = engine

    def validate_source_file(self, file_path: Path) -> None:
        """
        Cheap checks before calling the engine.

        They matter most for drag & drop, which can drop directories, images or
        empty files: without them, the first visible error would be a raw
        PyMuPDF exception.
        """
        if not file_path.exists():
            raise PdfNotFoundException(f"No se encuentra el archivo: {file_path}")

        if not file_path.is_file():
            raise InvalidPdfException(f"La ruta no es un archivo: {file_path}")

        if file_path.suffix.lower() != _PDF_SUFFIX:
            raise InvalidPdfException(
                f"'{file_path.name}' no es un PDF: se esperaba la extensión {_PDF_SUFFIX}."
            )

        if file_path.stat().st_size == 0:
            raise InvalidPdfException(f"El archivo está vacío: {file_path.name}")

    def open(self, file_path: Path) -> Document:
        """
        :raises PdfNotFoundException: If the path does not exist.
        :raises EncryptedPdfException: If the PDF asks for a password.
        :raises InvalidPdfException: If it is not a readable PDF or has no pages.
        """
        self.validate_source_file(file_path)

        try:
            doc = self._engine.open_document(file_path)
        except Exception as e:
            raise InvalidPdfException(
                f"No se pudo leer '{file_path.name}': el archivo está corrupto "
                f"o no es un PDF válido."
            ) from e

        try:
            if self._engine.needs_password(doc):
                raise EncryptedPdfException(
                    f"'{file_path.name}' está protegido con contraseña y no puede procesarse."
                )

            if not self._engine.is_pdf(doc):
                raise InvalidPdfException(
                    f"'{file_path.name}' no es un PDF, aunque tenga esa extensión."
                )

            if self._engine.get_page_count(doc) == 0:
                raise InvalidPdfException(f"'{file_path.name}' no contiene páginas.")
        except Exception:
            self._engine.close_document(doc)
            raise

        return doc
