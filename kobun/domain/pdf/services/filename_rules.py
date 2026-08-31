"""
Rules for naming the files Kobun produces.

They live in the domain and not in the UI because how an export is named is a
decision of the product —the user recognises "book_1-5.pdf" as something Kobun
made— and not a detail of the screen that asked for it.

Shared by the splitter and the asset extractor: both write files, and a name
that is safe in one has to be safe in the other.
"""
from pathlib import PurePath

PDF_SUFFIX = ".pdf"
FALLBACK_STEM = "kobun_split"

# Characters Windows forbids. Filtered always, not only on Windows, so a file
# exported on Linux stays copyable to another system.
_ILLEGAL_FILENAME_CHARS = frozenset('<>:"/\\|?*')


def sanitize_filename(value: str) -> str:
    """
    Replaces invalid characters with "_" and trims trailing dots and spaces,
    which Windows does not accept either.
    """
    cleaned = "".join(
        "_" if char in _ILLEGAL_FILENAME_CHARS or ord(char) < 32 else char
        for char in value
    )
    return cleaned.strip(" .")


def sanitized_stem(filename: str, fallback: str = FALLBACK_STEM) -> str:
    """
    The source name without its extension, safe to build a new name from.

    :param filename: Original filename, with or without a path.
    :param fallback: Used when sanitising leaves nothing usable, which happens
        with names made entirely of forbidden characters.
    """
    return sanitize_filename(PurePath(filename).stem) or fallback
