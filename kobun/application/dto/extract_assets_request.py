from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from kobun.domain.pdf.services.asset_extractor_service import DEFAULT_DPI
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode
from kobun.domain.pdf.value_objects.overwrite_policy import OverwritePolicy
from kobun.domain.pdf.value_objects.page_selection import PageSelection


@dataclass(frozen=True)
class ExtractAssetsRequest:
    """
    Everything needed to ask for an asset extraction.

    Same role as SplitPdfRequest, with one difference that shapes the whole
    feature: the destination is a **folder**, not a file, because a single page
    can produce several images.
    """

    input_path: Path
    selection: PageSelection

    mode: ExtractionMode = ExtractionMode.FIGURES

    output_directory: Optional[Path] = None
    """Folder to write the assets into. None uses a suggested folder next to
    the source PDF."""

    dpi: int = DEFAULT_DPI
    """Resolution for PAGE_RASTER. Ignored by EMBEDDED_IMAGES, which returns
    the stored bytes untouched."""

    policy: OverwritePolicy = OverwritePolicy.OVERWRITE
    """What to do when a **file** of the same name is already in the destination
    folder. Not about the folder: collecting several extractions in one folder is
    the normal case, and only a same-name file is a real conflict.

    Defaults to OVERWRITE, unlike a split, which defaults to FAIL. The names here
    are derived from the source, the page and the position, so a collision means
    that same asset was extracted before and replacing it is regenerating it. A
    split's name is chosen by the user and its contents differ, which is why
    destroying one silently would not be acceptable there."""

    def __post_init__(self) -> None:
        # Normalises strings to Path so the UI can pass whatever the folder
        # dialog gave it without converting by hand.
        object.__setattr__(self, "input_path", Path(self.input_path))

        if self.output_directory is not None:
            object.__setattr__(self, "output_directory", Path(self.output_directory))

        # A str Enum tolerates arriving as text from a combo box; the rest of
        # the system should still get the member.
        object.__setattr__(self, "mode", ExtractionMode(self.mode))
