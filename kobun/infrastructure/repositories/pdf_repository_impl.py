import hashlib
from pathlib import Path
from typing import Callable, Dict, List, Optional

from pymupdf import Document

from kobun.application.interfaces.pdf_repository import PdfRepository
from kobun.domain.pdf.entities.pdf_document import PdfDocument
from kobun.domain.pdf.value_objects.page_range import PageRange
from kobun.domain.pdf.value_objects.page_selection import PageSelection
from kobun.domain.pdf.value_objects.pdf_metadata import PdfMetadata
from kobun.infrastructure.pdf_engine.pdf_document_opener import PdfDocumentOpener
from kobun.infrastructure.pdf_engine.pdf_engine_adapter import PdfEngineAdapter

_CHUNK_SIZE = 4096


class PyMuPdfRepository(PdfRepository):
    """
    PdfRepository implementation over PyMuPDF, through PdfEngineAdapter.

    It bridges the domain (PdfDocument, PageSelection) and the PDF engine.
    Every page index it receives is 1-based.
    """

    def __init__(self, engine: PdfEngineAdapter, opener: Optional[PdfDocumentOpener] = None):
        self.engine = engine
        # Built from the engine when not supplied, so the existing callers that
        # pass only the engine keep working.
        self._opener = opener or PdfDocumentOpener(engine)

    # =========================
    # Internal Helpers
    # =========================

    def _calculate_checksum(self, file_path: Path) -> str:
        """
        Calculates SHA256 checksum of a file.

        :param file_path: Path to the file.
        :return: Hexadecimal checksum string.
        """
        sha256 = hashlib.sha256()

        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
                sha256.update(chunk)

        return sha256.hexdigest()

    def _open_engine_document(self, file_path: Path) -> Document:
        """
        Delegates to PdfDocumentOpener, which is shared with the asset
        extractor so both reject the same files with the same messages.
        """
        return self._opener.open(file_path)

    def _build_pdf_document(self, file_path: Path) -> PdfDocument:
        """
        Builds a PdfDocument entity from a file path.

        A file's metadata can arrive empty or incomplete. Mandatory fields get
        defaults and the rest is normalised to None: PdfMetadata rejects empty
        strings, and PyMuPDF returns "" for absent keys.

        `creationDate` is ignored on purpose: it comes in PDF format
        ("D:20260804120000Z") and there is no parser to datetime yet.

        The fallback title uses the name **without its extension**: it is a
        document title, not a filename, and dragging the ".pdf" along ended up
        producing titles like "contrato.pdf (3-6)" in what was exported.
        """
        doc = self._open_engine_document(file_path)

        try:
            raw_meta = self.engine.extract_metadata(doc) or {}
            page_count = self.engine.get_page_count(doc)
        finally:
            self.engine.close_document(doc)

        domain_metadata = PdfMetadata(
            title=raw_meta.get("title") or file_path.stem,
            author=raw_meta.get("author") or "Unknown",
            subject=raw_meta.get("subject") or "Unknown",
            keywords=raw_meta.get("keywords") or None,
            creator=raw_meta.get("creator") or None,
            producer=raw_meta.get("producer") or None,
        )

        return PdfDocument(
            filename=file_path.name,
            storage_path=file_path,
            metadata=domain_metadata,
            page_count=page_count,
            size_bytes=file_path.stat().st_size,
            checksum=self._calculate_checksum(file_path),
        )

    @staticmethod
    def _to_engine_metadata(metadata: PdfMetadata) -> Dict[str, Optional[str]]:
        """
        Translates the domain Value Object into the dictionary the engine
        expects.
        """
        return {
            "title": metadata.title,
            "author": metadata.author,
            "subject": metadata.subject,
            "keywords": metadata.keywords,
            "creator": metadata.creator,
            "producer": metadata.producer,
        }

    def _export(
        self,
        source_path: Path,
        build: Callable[[Document], Document],
        output_doc: Path,
        metadata: Optional[PdfMetadata] = None,
    ) -> PdfDocument:
        """
        Runs a derivation (split, extract, merge) and persists the result,
        guaranteeing both documents get closed.

        `new_doc` starts as None on purpose: if `build` fails, the `finally`
        must not break with UnboundLocalError and mask the engine's real
        error.
        """
        source = self._open_engine_document(source_path)
        new_doc: Optional[Document] = None

        try:
            new_doc = build(source)

            if metadata is not None:
                self.engine.set_metadata(new_doc, self._to_engine_metadata(metadata))

            self.engine.save_document(new_doc, output_doc)
        finally:
            self.engine.close_document(source)
            if new_doc is not None:
                self.engine.close_document(new_doc)

        return self._build_pdf_document(output_doc)

    # =========================
    # Repository API
    # =========================

    def open_document(self, file_path: Path) -> PdfDocument:
        """
        :raises PdfNotFoundException: If the path does not exist.
        :raises EncryptedPdfException: If the PDF asks for a password.
        :raises InvalidPdfException: If it is not a readable PDF or has no pages.
        """
        return self._build_pdf_document(file_path)

    def close_document(self, document: PdfDocument) -> None:
        """
        No-op for domain entity.

        Engine-level closing is handled internally.
        """
        pass

    def get_page_count(self, document: PdfDocument) -> int:
        """
        Returns the number of pages from the domain entity.
        """
        if document.page_count is None:
            raise ValueError("Page count is not initialized.")
        return document.page_count

    def extract_metadata(self, document: PdfDocument) -> PdfMetadata:
        """
        Returns metadata from the domain entity.
        """
        return document.metadata

    def extract_text(self, document: PdfDocument, page_number: int) -> str:
        """
        Extracts text from a specific page.

        :param page_number: 1-based page index.
        """
        doc = self._open_engine_document(document.storage_path)

        try:
            return self.engine.extract_text(doc, page_number)
        finally:
            self.engine.close_document(doc)

    def split_single_page(
        self,
        src_doc: PdfDocument,
        output_doc: Path,
        page_index: int
    ) -> PdfDocument:
        """
        Splits a single page into a new PDF.

        :param page_index: 1-based page index.
        """
        return self._export(
            source_path=src_doc.storage_path,
            build=lambda source: self.engine.split_single_page(source, page_index),
            output_doc=output_doc,
        )

    def split_page_range(
        self,
        src_doc: PdfDocument,
        output_doc: Path,
        page_range: PageRange
    ) -> PdfDocument:
        """
        Splits a contiguous range of pages into a new PDF.
        """
        return self._export(
            source_path=src_doc.storage_path,
            build=lambda source: self.engine.split_page_range(source, page_range),
            output_doc=output_doc,
        )

    def split_page_selection(
        self,
        src_doc: PdfDocument,
        output_doc: Path,
        selection: PageSelection,
        metadata: Optional[PdfMetadata] = None,
    ) -> PdfDocument:
        """
        Extracts a possibly discontinuous selection of ranges into a new PDF.
        """
        return self._export(
            source_path=src_doc.storage_path,
            build=lambda source: self.engine.extract_page_ranges(source, selection.ranges),
            output_doc=output_doc,
            metadata=metadata,
        )

    def merge_pdfs(
        self,
        first_doc: PdfDocument,
        second_doc: PdfDocument,
        output_doc: Path
    ) -> PdfDocument:
        """
        Merges two PDFs into a single document.
        """
        second: Optional[Document] = None

        try:
            second = self._open_engine_document(second_doc.storage_path)
            return self._export(
                source_path=first_doc.storage_path,
                build=lambda first: self.engine.merge_pdfs(first, second),
                output_doc=output_doc,
            )
        finally:
            if second is not None:
                self.engine.close_document(second)

    def extract_pages(
        self,
        document: PdfDocument,
        pages: List[int],
        output_doc: Path
    ) -> PdfDocument:
        """
        Extracts specific pages into a new PDF.

        :param pages: List of 1-based page indices.
        """
        return self._export(
            source_path=document.storage_path,
            build=lambda source: self.engine.extract_pages(source, pages),
            output_doc=output_doc,
        )
