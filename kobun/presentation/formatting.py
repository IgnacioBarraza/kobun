"""
Turning numbers into text a person reads.

Kept out of the widgets and free of Qt so the wording can be tested without
opening a window, same reason `error_messages` lives here: what the user reads
is worth a test, and a test that needs a QApplication tends not to get written.
"""
from kobun.domain.history.value_objects.export_kind import ExportKind

_UNITS = ("B", "KB", "MB", "GB", "TB")
_STEP = 1024

# Comma as the decimal separator, which is what Spanish uses. Formatting is done
# by hand rather than through `locale`: the module is global state, and a machine
# configured in English would silently start showing "1.2 MB".
_DECIMAL_SEPARATOR = ","

_ITEM_LABELS = {
    ExportKind.IMAGES: ("imagen", "imágenes"),
    ExportKind.PAGES: ("página PNG", "páginas PNG"),
}


def format_size(size_bytes: int) -> str:
    """
    A byte count as "912 B", "48,3 KB", "1,2 MB".

    Bytes get no decimals —"912,0 B" reads like a rounding of something— and
    everything above does, because that is where the digit carries information.
    """
    if size_bytes < 0:
        size_bytes = 0

    size = float(size_bytes)
    unit_index = 0

    while size >= _STEP and unit_index < len(_UNITS) - 1:
        size /= _STEP
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {_UNITS[0]}"

    return f"{size:.1f}".replace(".", _DECIMAL_SEPARATOR) + f" {_UNITS[unit_index]}"


def format_page_count(page_count: int) -> str:
    return "1 página" if page_count == 1 else f"{page_count} páginas"


def describe_items(kind: ExportKind, item_count: int) -> str:
    """
    What an export produced: "12 imágenes", "3 páginas PNG".

    Empty for a split, whose product is the single file already named beside
    it; saying "1 archivo" there would add a word and no information.
    """
    labels = _ITEM_LABELS.get(kind)
    if labels is None:
        return ""

    singular, plural = labels

    return f"{item_count} {singular if item_count == 1 else plural}"


def describe_export(kind: ExportKind, item_count: int, size_bytes: int) -> str:
    """
    The one-line summary of a finished export, for the result card and the
    history row.
    """
    items = describe_items(kind, item_count)
    size = format_size(size_bytes)

    return f"{items} · {size}" if items else size


def describe_replacements(replaced_count: int) -> str:
    """
    "2 reemplazados", or empty when nothing was replaced.

    Shown because the extraction screen replaces by default: a default that
    quietly overwrites should say how often it did.
    """
    if replaced_count <= 0:
        return ""

    return f"{replaced_count} reemplazado" + ("" if replaced_count == 1 else "s")
