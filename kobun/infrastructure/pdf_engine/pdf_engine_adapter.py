from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import pymupdf
from pymupdf import Document

from kobun.domain.pdf.value_objects.page_range import PageRange
from kobun.domain.pdf.value_objects.rectangle import Rectangle

# Metadata keys PyMuPDF understands and Kobun knows how to write.
_METADATA_KEYS = ("title", "author", "subject", "keywords", "creator", "producer")


class PdfEngineAdapter:
    """
    A thin wrapper over PyMuPDF.

    Index convention: every public method takes **1-based**, inclusive pages,
    same as the domain and the UI. Translating to PyMuPDF's 0-based indices
    happens exclusively inside this class.
    """

    def open_document(self, file_path: Path) -> Document:
        return pymupdf.open(file_path)

    def close_document(self, document: Document) -> None:
        document.close()

    def get_page_count(self, document: Document) -> int:
        return document.page_count

    def needs_password(self, document: Document) -> bool:
        """
        True if the document is encrypted and no password was supplied.
        """
        return bool(document.needs_pass)

    def is_pdf(self, document: Document) -> bool:
        """
        PyMuPDF also opens XPS, EPUB, CBZ and images. Kobun only works with
        PDFs, so it has to ask explicitly.
        """
        return bool(document.is_pdf)

    def extract_metadata(self, document: Document) -> Dict[str, Optional[str]]:
        return document.metadata

    def set_metadata(self, document: Document, metadata: Dict[str, Optional[str]]) -> None:
        """
        Writes metadata into the document, ignoring unknown or empty keys.
        """
        payload = {
            key: value
            for key, value in metadata.items()
            if key in _METADATA_KEYS and value
        }
        document.set_metadata(payload)

    def extract_text(self, document: Document, page_number: int) -> str:
        """
        :param page_number: 1-based page.
        """
        page = document.load_page(page_number - 1)
        return page.get_text("text")

    def create_empty_document(self) -> Document:
        return pymupdf.open()

    def split_single_page(self, src_doc: Document, page_index: int) -> Document:
        """
        :param page_index: 1-based page to extract.
        """
        return self.extract_page_ranges(src_doc, [PageRange(start=page_index, end=page_index)])

    def split_page_range(self, src_doc: Document, page_range: PageRange) -> Document:
        return self.extract_page_ranges(src_doc, [page_range])

    def extract_page_ranges(self, src_doc: Document, ranges: Sequence[PageRange]) -> Document:
        """
        Copies several contiguous ranges into a new document, in the order
        received.

        It uses one insertion per range instead of one per page, so extracting
        "1-500" costs one operation rather than five hundred.
        """
        new_doc = self.create_empty_document()

        for p_range in ranges:
            if p_range.end > src_doc.page_count:
                raise ValueError(
                    f"Page range {p_range} exceeds document length ({src_doc.page_count} pages)."
                )
            new_doc.insert_pdf(src_doc, from_page=p_range.start - 1, to_page=p_range.end - 1)

        return new_doc

    def merge_pdfs(self, first_doc: Document, second_doc: Document) -> Document:
        new_doc = self.create_empty_document()
        new_doc.insert_pdf(first_doc)
        new_doc.insert_pdf(second_doc)
        return new_doc

    def extract_pages(self, document: Document, pages: List[int]) -> Document:
        """
        :param pages: 1-based pages, in the order they should end up in.
        """
        new_doc = self.create_empty_document()

        for page in pages:
            if page < 1 or page > document.page_count:
                raise ValueError(f"Invalid page number: {page}")

            new_doc.insert_pdf(document, from_page=page - 1, to_page=page - 1)
        return new_doc

    # =========================
    # Assets
    # =========================

    def iter_page_image_xrefs(self, document: Document, page_number: int) -> Iterator[int]:
        """
        The xrefs of the raster images placed on a page.

        :param page_number: 1-based page.

        An xref is the identity of a stored object inside the PDF, which is what
        makes deduplication possible: a header logo repeated on every page is
        one xref referenced many times, not many images.

        `full=False` is enough here —only the xref is used— and it is the cheaper
        of the two forms.
        """
        page = document.load_page(page_number - 1)

        for entry in page.get_images(full=False):
            yield int(entry[0])

    def extract_image(self, document: Document, xref: int) -> Optional[Tuple[str, bytes, int, int]]:
        """
        The stored bytes of one image, in its original format.

        :return: (extension, data, width, height), or None if the xref does not
            resolve to a usable image.

        Never a lossy re-encode. What that means concretely depends on how the
        PDF stored the image: one kept as JPEG comes back as the *identical*
        JPEG stream, while one stored as raw flate-compressed samples —which has
        no file format of its own— is wrapped losslessly into a PNG. Either way
        no pixel is degraded, which is the property that matters when the user
        asked to extract the original.

        Returns None instead of raising because a PDF can reference an image
        object that is a mask, is broken, or is not extractable, and a single bad
        object must not abort an extraction that is otherwise working.
        """
        try:
            payload = document.extract_image(xref)
        except Exception:
            return None

        if not payload:
            return None

        data = payload.get("image")
        if not data:
            return None

        return (
            str(payload.get("ext") or "png"),
            bytes(data),
            int(payload.get("width") or 0),
            int(payload.get("height") or 0),
        )

    # =========================
    # Geometry
    # =========================

    @staticmethod
    def _to_rectangle(rect) -> Rectangle:
        """
        A PyMuPDF rect as the domain's own type.

        This conversion is the whole reason the domain can decide what a figure
        is: above this class, `pymupdf.Rect` does not exist.
        """
        return Rectangle(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))

    @staticmethod
    def _to_engine_rect(rectangle: Rectangle):
        return pymupdf.Rect(rectangle.x0, rectangle.y0, rectangle.x1, rectangle.y1)

    def page_bounds(self, document: Document, page_number: int) -> Rectangle:
        """
        :param page_number: 1-based page.
        """
        return self._to_rectangle(document.load_page(page_number - 1).rect)

    def page_drawing_boxes(self, document: Document, page_number: int) -> List[Rectangle]:
        """
        The bounding box of every vector drawing on a page.

        Only boxes: what the paths actually depict is not something the caller
        needs, and carrying the full path data of a dense page around costs a lot
        for nothing.
        """
        page = document.load_page(page_number - 1)

        return [self._to_rectangle(drawing["rect"]) for drawing in page.get_drawings()]

    def page_word_boxes(self, document: Document, page_number: int) -> List[Rectangle]:
        """
        The box of every word on a page.

        Words and not blocks: a block groups a whole paragraph, so an axis label
        sitting under a chart comes back fused with the line it shares, and no
        rule about "how much of it is inside the figure" can then tell them
        apart.
        """
        page = document.load_page(page_number - 1)

        return [
            self._to_rectangle(pymupdf.Rect(word[:4]))
            for word in page.get_text("words")
            if word[4].strip()
        ]

    def page_image_boxes(self, document: Document, page_number: int) -> List[Rectangle]:
        """
        Where the stored images are placed on the page.

        Used to recognise a vector drawing that is merely a frame around a photo,
        so the photo is not also handed back as a rendered crop.
        """
        page = document.load_page(page_number - 1)

        boxes = []
        for info in page.get_image_info():
            bbox = info.get("bbox")
            if bbox:
                boxes.append(self._to_rectangle(pymupdf.Rect(bbox)))

        return boxes

    def cluster_drawing_boxes(
        self,
        document: Document,
        page_number: int,
        boxes: Sequence[Rectangle],
    ) -> List[Rectangle]:
        """
        Groups nearby drawings into the regions they form, which is what turns
        four hundred little paths into "two figures".

        The engine does the grouping; **which drawings go in is the caller's
        decision**, and it matters: leave a page border in and everything it
        encloses merges with it, so the page comes back as one figure.
        """
        page = document.load_page(page_number - 1)
        engine_boxes = [
            {"rect": self._to_engine_rect(box), "type": "f", "items": []}
            for box in boxes
        ]

        if not engine_boxes:
            return []

        return [
            self._to_rectangle(rect)
            for rect in page.cluster_drawings(drawings=engine_boxes)
        ]

    def render_region_png(
        self,
        document: Document,
        page_number: int,
        region: Rectangle,
        dpi: int,
    ) -> Tuple[bytes, int, int]:
        """
        One region of a page painted into a PNG.

        This is the answer to a figure that exists only as vector art: it cannot
        be copied out, but it can be drawn — and drawing *its region* rather than
        the whole page is what makes the result a figure instead of a screenshot.

        :param page_number: 1-based page.
        :return: (data, width, height).
        """
        page = document.load_page(page_number - 1)
        pixmap = page.get_pixmap(clip=self._to_engine_rect(region), dpi=dpi)

        return pixmap.tobytes("png"), pixmap.width, pixmap.height

    def render_page_to_width(
        self,
        document: Document,
        page_number: int,
        target_width: int,
    ) -> Tuple[bytes, int, int]:
        """
        A page painted so it comes out `target_width` pixels across.

        Sized by a zoom factor derived from the page's own width instead of by a
        resolution: a preview has to fit a panel, and pages are not all the same
        size —A4, letter, a slide, a scanned receipt— so the same dpi would give
        each of them a different width.

        :param page_number: 1-based page.
        :return: (data, width, height).
        """
        page = document.load_page(page_number - 1)
        page_width = page.rect.width

        # A degenerate page rect would make the zoom explode or divide by zero.
        zoom = (target_width / page_width) if page_width > 0 else 1.0
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))

        return pixmap.tobytes("png"), pixmap.width, pixmap.height

    def render_page_png(self, document: Document, page_number: int, dpi: int) -> Tuple[bytes, int, int]:
        """
        A whole page painted into a PNG: vectors, text and images together.

        :param page_number: 1-based page.
        :param dpi: Resolution. The caller is responsible for it being sane;
            the domain caps it, because at 600 dpi an A4 page is already some
            35 megapixels.
        :return: (data, width, height).

        PNG and not JPEG: a rendered page is mostly text on a flat background,
        which is exactly the case where lossless compresses better and JPEG
        leaves visible artefacts around the glyphs.
        """
        page = document.load_page(page_number - 1)
        pixmap = page.get_pixmap(dpi=dpi)

        return pixmap.tobytes("png"), pixmap.width, pixmap.height

    def save_document(self, document: Document, path: Path) -> None:
        document.save(path)
