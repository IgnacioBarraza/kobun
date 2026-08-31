from typing import Iterator, List, Optional, Set

from kobun.application.dto.extracted_asset import ExtractedAsset
from kobun.application.interfaces.pdf_asset_extractor import PdfAssetExtractor
from kobun.domain.pdf.entities.pdf_document import PdfDocument
from kobun.domain.pdf.services import figure_rules
from kobun.domain.pdf.value_objects.asset_origin import AssetOrigin
from kobun.domain.pdf.value_objects.page_selection import PageSelection
from kobun.domain.pdf.value_objects.rectangle import Rectangle
from kobun.infrastructure.pdf_engine.pdf_document_opener import PdfDocumentOpener
from kobun.infrastructure.pdf_engine.pdf_engine_adapter import PdfEngineAdapter


class PyMuPdfAssetExtractor(PdfAssetExtractor):
    """
    PdfAssetExtractor implementation over PyMuPDF.

    It shares PdfDocumentOpener with PyMuPdfRepository, so a file rejected for
    splitting is rejected here with the same message.

    Both methods are generators, which the port requires: the document stays
    open for as long as the caller is iterating, and closing it is tied to the
    generator finishing —including when the caller abandons it— through the
    `finally`. Without that, an interrupted export would leak the handle and,
    on Windows, leave the PDF locked.
    """

    def __init__(self, engine: PdfEngineAdapter, opener: Optional[PdfDocumentOpener] = None):
        self._engine = engine
        self._opener = opener or PdfDocumentOpener(engine)

    def iter_embedded_images(
        self,
        document: PdfDocument,
        selection: PageSelection,
    ) -> Iterator[ExtractedAsset]:
        source = self._opener.open(document.storage_path)

        # Deduplication spans the whole run and not each page: that is the
        # point. A logo in the header is one stored object referenced by every
        # page, and yielding it once per page would bury the real figures.
        seen: Set[int] = set()

        try:
            for page_number in selection.to_pages():
                yield from self._page_embedded_images(source, page_number, seen)
        finally:
            self._engine.close_document(source)

    def iter_figures(
        self,
        document: PdfDocument,
        selection: PageSelection,
        dpi: int,
    ) -> Iterator[ExtractedAsset]:
        source = self._opener.open(document.storage_path)
        seen: Set[int] = set()

        try:
            for page_number in selection.to_pages():
                yield from self._page_embedded_images(source, page_number, seen)
                yield from self._page_vector_figures(source, page_number, dpi)
        finally:
            self._engine.close_document(source)

    def _page_vector_figures(
        self,
        source,
        page_number: int,
        dpi: int,
    ) -> Iterator[ExtractedAsset]:
        """
        The vector artwork on a page, one rendered crop per figure.

        The engine supplies the raw geometry and the grouping; every judgement
        —what is page furniture, what is too small, where the crop's edges go,
        which regions are the same figure— comes from `figure_rules`, so it can
        be tested exhaustively without a PDF in sight.
        """
        bounds = self._engine.page_bounds(source, page_number)

        usable = figure_rules.usable_drawings(
            self._engine.page_drawing_boxes(source, page_number), bounds
        )
        if not usable:
            return

        image_boxes = self._engine.page_image_boxes(source, page_number)
        words = self._engine.page_word_boxes(source, page_number)

        candidates: List[Rectangle] = [
            figure_rules.with_labels(cluster, words, bounds)
            for cluster in self._engine.cluster_drawing_boxes(source, page_number, usable)
            if figure_rules.is_figure_candidate(cluster, bounds)
            and not figure_rules.drops_duplicate_of_image(cluster, image_boxes)
        ]

        for sequence, region in enumerate(figure_rules.merge_overlapping(candidates), start=1):
            data, width, height = self._engine.render_region_png(
                source, page_number, region, dpi
            )

            yield ExtractedAsset(
                page_number=page_number,
                origin=AssetOrigin.FIGURE,
                sequence=sequence,
                extension="png",
                data=data,
                width=width,
                height=height,
            )

    def _page_embedded_images(
        self,
        source,
        page_number: int,
        seen: Set[int],
    ) -> Iterator[ExtractedAsset]:
        """
        The stored images of one page, skipping the xrefs already handed over.

        `seen` is owned by the caller so deduplication spans the whole run: a
        header logo is one stored object referenced by every page.
        """
        sequence = 0

        for xref in self._engine.iter_page_image_xrefs(source, page_number):
            if xref in seen:
                continue
            seen.add(xref)

            payload = self._engine.extract_image(source, xref)
            if payload is None:
                continue

            extension, data, width, height = payload
            sequence += 1

            yield ExtractedAsset(
                page_number=page_number,
                origin=AssetOrigin.EMBEDDED,
                sequence=sequence,
                extension=extension,
                data=data,
                width=width,
                height=height,
            )

    def iter_page_renders(
        self,
        document: PdfDocument,
        selection: PageSelection,
        dpi: int,
    ) -> Iterator[ExtractedAsset]:
        source = self._opener.open(document.storage_path)

        try:
            for page_number in selection.to_pages():
                data, width, height = self._engine.render_page_png(source, page_number, dpi)

                yield ExtractedAsset(
                    page_number=page_number,
                    origin=AssetOrigin.PAGE,
                    sequence=1,
                    extension="png",
                    data=data,
                    width=width,
                    height=height,
                )
        finally:
            self._engine.close_document(source)
