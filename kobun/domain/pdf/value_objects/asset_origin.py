from enum import Enum


class AssetOrigin(str, Enum):
    """
    Where a produced file came from, which is not the same question as which
    mode was asked for: the figures mode returns both stored images and rendered
    crops, and they deserve to be told apart in the folder.
    """

    EMBEDDED = "embedded"
    """Bytes the PDF had stored. Named `_img01`."""

    FIGURE = "figure"
    """A region of the page rendered because the figure is vector art with no
    stored image behind it. Named `_fig01`."""

    PAGE = "page"
    """A whole page rendered. One per page, so it carries no index."""

    @property
    def filename_infix(self) -> str:
        """
        The part of the name that says what the file is. Empty for a whole page,
        which needs no index because there is only ever one per page.
        """
        return {
            AssetOrigin.EMBEDDED: "img",
            AssetOrigin.FIGURE: "fig",
            AssetOrigin.PAGE: "",
        }[self]

    @property
    def is_rendered(self) -> bool:
        """Whether Kobun painted the pixels, rather than copying stored ones."""
        return self is not AssetOrigin.EMBEDDED
