from abc import ABC, abstractmethod
from typing import Iterator

from kobun.application.dto.extracted_asset import ExtractedAsset
from kobun.domain.pdf.entities.pdf_document import PdfDocument
from kobun.domain.pdf.value_objects.page_selection import PageSelection


class PdfAssetExtractor(ABC):
    """
    Pulling images out of a PDF, as the application sees it.

    Kept apart from PdfRepository instead of grown into it: that interface is
    already wider than its use, and the two contracts have different shapes.
    A repository returns documents; this returns a stream of files.

    Every page index is 1-based, same as everywhere else in Kobun.

    Implementations **must** yield lazily. The use case writes each asset as it
    arrives, and that is the only thing keeping a large export from holding
    hundreds of decoded images in memory at once.
    """

    @abstractmethod
    def iter_embedded_images(
        self,
        document: PdfDocument,
        selection: PageSelection,
    ) -> Iterator[ExtractedAsset]:
        """
        The raster images the PDF stores in the selected pages, never lossily
        re-encoded: a stored JPEG comes back as the identical JPEG, and an image
        the PDF keeps as raw compressed samples is wrapped losslessly into PNG.

        An image reused across pages —a logo in the header— is yielded once,
        attributed to the first page it appears on. It is the same stored
        object, and handing back one copy per page is not what anyone asking
        for "the images in this document" means.

        Vector drawings are not embedded images and do not appear here.
        """
        pass

    @abstractmethod
    def iter_figures(
        self,
        document: PdfDocument,
        selection: PageSelection,
        dpi: int,
    ) -> Iterator[ExtractedAsset]:
        """
        Every picture on the selected pages, whatever it is made of.

        Two sources, in this order per page:

        1. The stored images, exactly as `iter_embedded_images` returns them.
           When the picture exists as data, that data is what the user wants.
        2. The vector artwork, rendered from the region of the page it occupies.
           A chart drawn with lines and fills is not a stored image and cannot
           be handed over any other way — but rendering *just its region* is not
           the same as rendering the page, which is the whole point.

        A vector region that turns out to be a frame drawn around a stored image
        is not returned twice: the stored bytes win.
        """
        pass

    @abstractmethod
    def iter_page_renders(
        self,
        document: PdfDocument,
        selection: PageSelection,
        dpi: int,
    ) -> Iterator[ExtractedAsset]:
        """
        Each selected page painted into a single PNG, vectors and text
        included.

        Exactly one asset per page, in the selection's order.
        """
        pass
