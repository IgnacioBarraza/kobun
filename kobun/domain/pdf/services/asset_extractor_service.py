from kobun.domain.pdf.entities.pdf_document import PdfDocument
from kobun.domain.pdf.exceptions.invalid_extraction_exception import InvalidExtractionException
from kobun.domain.pdf.services import selection_rules
from kobun.domain.pdf.services.filename_rules import sanitized_stem
from kobun.domain.pdf.value_objects.asset_origin import AssetOrigin
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode
from kobun.domain.pdf.value_objects.page_selection import PageSelection

DEFAULT_DPI = 150
"""Enough to read the page on screen and to print it acceptably, without the
file weighing what a 300 dpi scan does."""

MIN_DPI = 36
MAX_DPI = 600
"""Cap chosen against memory, not against quality: an A4 page at 600 dpi is
already ~35 megapixels, and a 40 page selection past that starts swapping."""

MIN_IMAGE_SIDE = 16
"""Images smaller than this on either side are dropped.

PDFs are full of 1x1 spacers, rules and bullet glyphs stored as images. Handing
the user 300 files of which 280 are invisible slivers makes the feature useless,
and 16 pixels is below anything anyone would call a figure."""

FALLBACK_STEM = "kobun"
"""Used when the source name sanitises to nothing. Its own, and not the
splitter's: "kobun_split_imagenes_1" describes an operation that did not
happen."""

MODE_FOLDER_LABELS = {
    ExtractionMode.FIGURES: "figuras",
    ExtractionMode.EMBEDDED_IMAGES: "imagenes",
    ExtractionMode.PAGE_RASTER: "paginas",
}


class AssetExtractorService:
    """
    Domain Service for the rules of pulling images out of a PDF.

    Same contract as PdfSplitterService: it knows neither PyMuPDF nor the
    filesystem. It decides what is legitimate to ask for, what is worth
    keeping, and what the produced files are called.
    """

    def validate_request(
        self,
        document: PdfDocument,
        selection: PageSelection,
        mode: ExtractionMode,
        dpi: int,
    ) -> None:
        """
        :raises InvalidPdfException: If the document is unusable.
        :raises InvalidPageRangeException: If the selection goes past the last page.
        :raises InvalidExtractionException: If the resolution is out of range.
        """
        selection_rules.validate_selection(document, selection)

        # Validated for both modes even though only the raster one uses it: a
        # nonsense value that silently does nothing in one mode and breaks in
        # the other is worse than a consistent error.
        self.validate_dpi(dpi)

        if not isinstance(mode, ExtractionMode):
            raise InvalidExtractionException(f"Modo de extracción desconocido: {mode!r}.")

    @staticmethod
    def validate_dpi(dpi: int) -> None:
        if not isinstance(dpi, int) or isinstance(dpi, bool):
            raise InvalidExtractionException("La resolución debe ser un número entero de dpi.")

        if dpi < MIN_DPI or dpi > MAX_DPI:
            raise InvalidExtractionException(
                f"La resolución debe estar entre {MIN_DPI} y {MAX_DPI} dpi. Se pidió: {dpi}."
            )

    @staticmethod
    def is_significant_image(width: int, height: int) -> bool:
        """
        Whether an embedded image is worth handing to the user.

        See MIN_IMAGE_SIDE: this is what keeps an export from being mostly
        invisible spacers.
        """
        return min(width, height) >= MIN_IMAGE_SIDE

    def suggest_output_directory_name(
        self,
        source_doc: PdfDocument,
        mode: ExtractionMode,
    ) -> str:
        """
        Name of the folder the assets go into: "libro_figuras".

        A folder and not loose files next to the PDF: an extraction can write
        forty files, and dropping them into the source's directory would bury
        it.

        The **selection is deliberately not part of the name.** It used to be,
        and that made the suggestion change on every run: extracting pages 1-5
        and then 6-10 produced two folders, when what anyone doing that wants is
        one folder with everything in it. The page each file came from is
        already in the file's own name, so nothing is lost by leaving it out
        here.
        """
        stem = sanitized_stem(source_doc.filename, FALLBACK_STEM)

        return f"{stem}_{MODE_FOLDER_LABELS[mode]}"

    def asset_filename(
        self,
        source_doc: PdfDocument,
        page_number: int,
        sequence: int,
        extension: str,
        origin: AssetOrigin,
    ) -> str:
        """
        Name of one produced file: "libro_p007_img02.png", "libro_p007_fig01.png",
        "libro_p007.png".

        Zero padded on purpose, so the file manager's alphabetical order matches
        the document's. Without the padding, page 10 sorts before page 2 and the
        folder becomes unreadable.

        Keyed on the origin and not on the mode, because one mode can produce
        both: the figures mode returns stored images *and* rendered crops, and a
        folder where the two are indistinguishable hides which files are the
        originals.

        :param page_number: 1-based page the asset came from.
        :param sequence: 1-based position among the assets of the same origin on
            that page. Ignored for a whole page, of which there is only one.
        :param extension: Format the engine reported, with or without a dot.
        """
        stem = sanitized_stem(source_doc.filename, FALLBACK_STEM)
        page_part = f"p{page_number:03d}"
        suffix = self._normalize_extension(extension)
        infix = origin.filename_infix

        if not infix:
            return f"{stem}_{page_part}{suffix}"

        return f"{stem}_{page_part}_{infix}{sequence:02d}{suffix}"

    @staticmethod
    def _normalize_extension(extension: str) -> str:
        """
        The engine reports "png" and "jpeg" without a dot, but a caller passing
        ".png" should not end up with "..png".
        """
        cleaned = sanitized_stem(extension.strip().lstrip("."), fallback="bin").lower()

        return f".{cleaned}" if cleaned else ".bin"
