"""
Translating exceptions into messages for the user.

It separates two things that must not be confused:

- **Expected errors**: the user asked for something that cannot be done. They
  are shown as they are, and the application keeps running.
- **Unexpected errors**: a bug of ours. A generic text is shown and the detail
  is kept for the log, because a traceback on screen helps nobody and
  swallowing the exception silently is worse.

This distinction is possible because the domain guarantees it only lets its own
exceptions escape; anything else is, by definition, a bug.
"""
from dataclasses import dataclass
from typing import Dict, Optional, Type

from kobun.domain.history.exceptions.invalid_export_record_exception import (
    InvalidExportRecordException,
)
from kobun.domain.pdf.exceptions.encrypted_pdf_exception import EncryptedPdfException
from kobun.domain.pdf.exceptions.file_open_exception import FileOpenException
from kobun.domain.pdf.exceptions.invalid_extraction_exception import (
    InvalidExtractionException,
)
from kobun.domain.pdf.exceptions.invalid_output_path_exception import InvalidOutputPathException
from kobun.domain.pdf.exceptions.invalid_page_range_exception import InvalidPageRangeException
from kobun.domain.pdf.exceptions.invalid_pdf_exception import InvalidPdfException
from kobun.domain.pdf.exceptions.invalid_pdf_metadata_exception import (
    InvalidPdfMetadataException,
)
from kobun.domain.pdf.exceptions.pdf_not_found_exception import PdfNotFoundException

UNEXPECTED_ERROR_MESSAGE = (
    "Ocurrió un error inesperado. Si vuelve a pasar, reportalo con el detalle técnico."
)

# Errors the user can cause and fix. The order does not matter: the lookup is
# by exact type first and then by inheritance.
EXPECTED_ERRORS = (
    PdfNotFoundException,
    EncryptedPdfException,
    InvalidPdfException,
    InvalidPdfMetadataException,
    InvalidPageRangeException,
    InvalidOutputPathException,
    InvalidExtractionException,
    FileOpenException,
    InvalidExportRecordException,
)

# Texts that replace the domain's message when the UI wants a different tone.
# Anything not here uses the original message, which is already readable.
_OVERRIDES: Dict[Type[Exception], str] = {
    EncryptedPdfException: (
        "El PDF está protegido con contraseña. Quitale la protección e intentá de nuevo."
    ),
}


def is_expected(error: Exception) -> bool:
    """
    True if the error is part of the application's normal use and not a bug.
    """
    return isinstance(error, EXPECTED_ERRORS)


def translate(error: Exception) -> str:
    """
    The message to show the user.

    :param error: The exception caught in the presentation layer.
    """
    if not is_expected(error):
        return UNEXPECTED_ERROR_MESSAGE

    for error_type, message in _OVERRIDES.items():
        if isinstance(error, error_type):
            return message

    return str(error) or UNEXPECTED_ERROR_MESSAGE


def technical_detail(error: Exception) -> str:
    """
    Detail for the log or for a "see more" panel. Never the main message.
    """
    return f"{type(error).__name__}: {error}"


EXPECTED_TITLE = "No se pudo completar la operación"
UNEXPECTED_TITLE = "Error inesperado"


@dataclass(frozen=True)
class ErrorPrompt:
    """
    What to show in an error dialog, decided without depending on Qt.

    Separating the decision from the presentation makes the policy testable
    —which title, which icon, whether technical detail is offered— without
    opening windows.
    """

    title: str
    message: str
    is_critical: bool
    detail: Optional[str] = None


def build_error_prompt(error: Exception) -> ErrorPrompt:
    """
    Translates an exception into the contents of its dialog.

    Expected errors are warnings whose message is already good to go.
    Unexpected ones are critical and carry the technical detail separately, so
    the user can copy it when reporting without having to read it.
    """
    expected = is_expected(error)

    return ErrorPrompt(
        title=EXPECTED_TITLE if expected else UNEXPECTED_TITLE,
        message=translate(error),
        is_critical=not expected,
        detail=None if expected else technical_detail(error),
    )
