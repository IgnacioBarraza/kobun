from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Tuple

from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode
from kobun.domain.pdf.value_objects.page_selection import PageSelection


@dataclass(frozen=True)
class ExtractAssetsResponse:
    """
    The result of an extraction: what was asked, what came out, and when.

    `files` can be **empty**, and that is a legitimate outcome rather than a
    failure: a selection of pages carrying only vector drawings has no embedded
    images to give. The UI is expected to say so plainly instead of reporting
    an error, which is why this is a normal response and not an exception.
    """

    source_path: Path
    selection: PageSelection
    mode: ExtractionMode

    output_directory: Path
    """The folder actually written to. It can differ from the requested one if
    the overwrite policy had to look for a free name."""

    files: Tuple[Path, ...]
    total_size_bytes: int
    completed_at: datetime

    replaced_count: int = 0
    """How many of those files replaced one that was already there.

    Reported rather than left silent: the extraction screen replaces by default
    —the names are derived from the source, so a collision is the same asset
    extracted again— and a default that quietly overwrites should at least say
    how often it did."""

    @property
    def source_filename(self) -> str:
        return self.source_path.name

    @property
    def asset_count(self) -> int:
        return len(self.files)

    @property
    def found_nothing(self) -> bool:
        return not self.files

    @property
    def pages_requested(self) -> int:
        return self.selection.total_pages

    def __str__(self) -> str:
        return (
            f"{self.source_filename} [{self.selection}] -> "
            f"{self.asset_count} archivos en {self.output_directory.name}"
        )
