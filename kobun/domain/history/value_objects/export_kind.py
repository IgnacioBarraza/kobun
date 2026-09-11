from enum import Enum


class ExportKind(str, Enum):
    """
    What kind of export a history entry describes.

    It exists because the history stopped being homogeneous: a split produces
    one PDF and an extraction produces a folder of images. Without this, the UI
    would have to guess from the path whether "open" means launching a viewer or
    showing a folder — and guessing from a path is how you end up trying to open
    a directory as a document.

    A str Enum so old entries, which carry no kind at all, can default to SPLIT
    when read back.
    """

    SPLIT = "split"
    """One PDF extracted from a page selection."""

    IMAGES = "images"
    """The images embedded in a page selection, written into a folder."""

    PAGES = "pages"
    """A page selection rendered to PNG, written into a folder."""

    @property
    def outputs_directory(self) -> bool:
        """
        True when `output_path` points at a folder rather than a file. Decides
        whether the entry is opened in a viewer or shown in the file manager.
        """
        return self is not ExportKind.SPLIT
