from dataclasses import dataclass

from kobun.domain.pdf.value_objects.asset_origin import AssetOrigin


@dataclass(frozen=True)
class ExtractedAsset:
    """
    One file the engine produced, before it has a name or a place on disk.

    It travels with its bytes rather than with a path because the extractor
    does not decide where things are written: naming is a domain rule and
    writing is the use case's job. That also lets the extractor be a generator,
    so a 400 page selection holds one image in memory at a time instead of all
    of them.
    """

    page_number: int
    """1-based page the asset came from."""

    origin: AssetOrigin
    """Whether these bytes were stored in the PDF or painted by Kobun. Decides
    the file's name, and lets one mode return both without the folder becoming
    ambiguous."""

    sequence: int
    """1-based position within its page, so several images on one page get
    distinguishable names."""

    extension: str
    """Format as the engine reported it: "png", "jpeg". No dot."""

    data: bytes

    width: int = 0
    height: int = 0
    """Pixel dimensions, when the engine knows them. Zero means unknown, which
    is why the significance filter treats them as such."""

    @property
    def size_bytes(self) -> int:
        return len(self.data)
