from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from kobun.application.dto.extract_assets_request import ExtractAssetsRequest
from kobun.application.dto.extract_assets_response import ExtractAssetsResponse
from kobun.application.dto.extracted_asset import ExtractedAsset
from kobun.application.interfaces.file_storage import FileStorage
from kobun.application.interfaces.pdf_asset_extractor import PdfAssetExtractor
from kobun.application.interfaces.pdf_repository import PdfRepository
from kobun.application.services.output_directory_resolver import OutputDirectoryResolver
from kobun.domain.pdf.entities.pdf_document import PdfDocument
from kobun.domain.pdf.exceptions.invalid_output_path_exception import (
    InvalidOutputPathException,
)
from kobun.domain.pdf.services.asset_extractor_service import AssetExtractorService
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode
from kobun.domain.pdf.value_objects.overwrite_policy import OverwritePolicy


class ExtractAssetsUseCase:
    """
    Orchestrates pulling images out of a page selection: validates the source,
    resolves the destination folder, and writes each asset as the extractor
    yields it.

    Written as a streaming loop and not as "collect then save" on purpose: a
    300 page raster at 300 dpi is several gigabytes of pixels, and holding them
    all before the first write is the difference between working and dying.
    """

    def __init__(
        self,
        pdf_repository: PdfRepository,
        asset_extractor: PdfAssetExtractor,
        asset_service: AssetExtractorService,
        output_directory_resolver: OutputDirectoryResolver,
        file_storage: FileStorage,
    ):
        self._pdf_repository = pdf_repository
        self._asset_extractor = asset_extractor
        self._asset_service = asset_service
        self._output_directory_resolver = output_directory_resolver
        self._file_storage = file_storage

    def execute(self, request: ExtractAssetsRequest) -> ExtractAssetsResponse:
        """
        :param request: Source, page selection, mode, destination and overwrite
            policy.
        :return: A description of the operation, including an empty file list
            when the pages held nothing extractable.
        """
        document = self._pdf_repository.open_document(request.input_path)

        self._asset_service.validate_request(
            document, request.selection, request.mode, request.dpi
        )
        target = self._resolve_output(document, request)

        document.mark_as_processing()

        try:
            files, total_bytes, replaced = self._write_assets(document, request, target)

            if not files:
                # Nothing came out, so the folder that was created to hold it
                # has no reason to stay. Only removed if empty, which also
                # means an OVERWRITE into a folder that already had files
                # leaves it alone.
                self._file_storage.remove_directory_if_empty(target)

            document.mark_as_processed()
            return ExtractAssetsResponse(
                source_path=document.storage_path,
                selection=request.selection,
                mode=request.mode,
                output_directory=target,
                files=tuple(files),
                total_size_bytes=total_bytes,
                completed_at=datetime.now(timezone.utc),
                replaced_count=replaced,
            )

        except Exception:
            document.mark_as_failed()
            raise

    def suggest_output_directory(
        self,
        document: PdfDocument,
        mode: ExtractionMode,
        parent: Optional[Path] = None,
    ) -> Path:
        """
        The folder that would be used by default, to prefill the UI. It touches
        no disk.

        It does not depend on the selection, so extracting pages 1-5 and then
        6-10 suggests the same folder both times and everything ends up
        together.
        """
        base = parent or document.storage_path.parent

        return base / self._asset_service.suggest_output_directory_name(document, mode)

    def _resolve_output(self, document: PdfDocument, request: ExtractAssetsRequest) -> Path:
        """
        Resolved before marking the document as PROCESSING, for the same reason
        as in SplitPdfUseCase: an unusable destination means the operation never
        started, and the document's state must not claim it failed.
        """
        requested = request.output_directory or self.suggest_output_directory(
            document, request.mode
        )

        return self._output_directory_resolver.resolve(requested)

    def _write_assets(
        self,
        document: PdfDocument,
        request: ExtractAssetsRequest,
        target: Path,
    ) -> tuple:
        """
        Consumes the extractor and writes each asset under its domain name.

        The sequence number is per page **and per origin**, and counts only what
        was kept: names stay contiguous —img01, img02— even when the filter
        dropped an invisible spacer in between, and a page holding both a stored
        image and a vector figure numbers them separately.
        """
        written: List[Path] = []
        replaced = 0
        total_bytes = 0
        sequences: Dict[tuple, int] = {}

        for asset in self._select(document, request):
            key = (asset.page_number, asset.origin)
            sequences[key] = sequences.get(key, 0) + 1

            filename = self._asset_service.asset_filename(
                source_doc=document,
                page_number=asset.page_number,
                sequence=sequences[key],
                extension=asset.extension,
                origin=asset.origin,
            )

            path, existed = self._resolve_asset_path(target / filename, request.policy)
            self._file_storage.write_bytes(path, asset.data)

            written.append(path)
            replaced += 1 if existed else 0
            total_bytes += asset.size_bytes

        return written, total_bytes, replaced

    def _resolve_asset_path(self, path: Path, policy: OverwritePolicy) -> tuple:
        """
        Where one asset goes, and whether something was already there.

        A collision here is narrower than it looks: the name is derived from the
        source, the page and the position, so a file of that name in the chosen
        folder is almost always the same asset extracted before. That is why
        OVERWRITE is a sane default for an extraction while it would not be for
        a split, whose name the user chose and whose contents differ.

        :return: (path to write, whether a file was already there)
        """
        if not self._file_storage.exists(path):
            return path, False

        if policy == OverwritePolicy.OVERWRITE:
            return path, True

        if policy == OverwritePolicy.RENAME:
            return self._file_storage.unique_path(path), False

        raise InvalidOutputPathException(
            f"Ya existe un archivo llamado '{path.name}' en la carpeta de destino. "
            f"Elegí otra carpeta, o permití reemplazar o renombrar."
        )

    def _select(
        self,
        document: PdfDocument,
        request: ExtractAssetsRequest,
    ) -> Iterator[ExtractedAsset]:
        """
        Picks the extractor method for the mode and applies the significance
        filter, which is a domain rule and therefore not the engine's business.

        The filter only ever drops *stored* images: a rendered asset exists
        because something was found worth rendering, and its pixel size is a
        consequence of the resolution rather than of the source.
        """
        if request.mode is ExtractionMode.PAGE_RASTER:
            return self._asset_extractor.iter_page_renders(
                document, request.selection, request.dpi
            )

        if request.mode is ExtractionMode.FIGURES:
            stream = self._asset_extractor.iter_figures(
                document, request.selection, request.dpi
            )
        else:
            stream = self._asset_extractor.iter_embedded_images(
                document, request.selection
            )

        return (asset for asset in stream if self._is_worth_keeping(asset))

    def _is_worth_keeping(self, asset: ExtractedAsset) -> bool:
        if asset.origin.is_rendered:
            return True

        return self._asset_service.is_significant_image(asset.width, asset.height)
