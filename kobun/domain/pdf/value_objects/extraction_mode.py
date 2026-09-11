from enum import Enum


class ExtractionMode(str, Enum):
    """
    What to pull out of the selected pages.

    The three modes answer different questions, which is why the user picks
    instead of Kobun guessing:

    - FIGURES is "give me the pictures, whatever they are made of": the stored
      images, plus the vector artwork rendered as its own cropped PNG. It is the
      default because it is what people mean by "extract the images".
    - EMBEDDED_IMAGES is the strict one: only what the PDF actually stores, so
      nothing on disk was painted by Kobun.
    - PAGE_RASTER is the fallback that always produces something, at the cost of
      handing back whole pages rather than figures.

    A str Enum so it survives a round trip through a Qt combo box or a
    configuration file as plain text.
    """

    FIGURES = "figures"
    """Stored images, plus vector figures rendered from the region they occupy."""

    EMBEDDED_IMAGES = "embedded_images"
    """Only the raster images the PDF stores, in their stored bytes."""

    PAGE_RASTER = "page_raster"
    """Each selected page rendered whole, at the requested resolution."""

    @property
    def produces_one_file_per_page(self) -> bool:
        """
        True when each page yields exactly one file, which lets the UI predict
        how many files an export will write.
        """
        return self is ExtractionMode.PAGE_RASTER

    @property
    def includes_embedded_images(self) -> bool:
        return self in (ExtractionMode.FIGURES, ExtractionMode.EMBEDDED_IMAGES)

    @property
    def renders_anything(self) -> bool:
        """
        Whether the mode paints pixels and therefore cares about the resolution.
        """
        return self in (ExtractionMode.FIGURES, ExtractionMode.PAGE_RASTER)
