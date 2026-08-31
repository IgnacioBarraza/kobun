import pytest

from kobun.domain.history.value_objects.export_kind import ExportKind
from kobun.presentation import formatting


# =========================
# Tamaños
# =========================

@pytest.mark.parametrize(
    "size, expected",
    [
        (0, "0 B"),
        (1, "1 B"),
        (999, "999 B"),
        (1024, "1,0 KB"),
        (49_500, "48,3 KB"),
        (1_290_000, "1,2 MB"),
        (5_400_000_000, "5,0 GB"),
    ],
)
def test_sizes_are_scaled_to_a_readable_unit(size, expected):
    assert formatting.format_size(size) == expected


def test_bytes_get_no_decimals():
    """"912,0 B" reads like a rounding of something; a byte count is exact."""
    assert formatting.format_size(912) == "912 B"


def test_the_decimal_separator_is_a_comma():
    """Spanish, and independent of the machine's locale."""
    assert "," in formatting.format_size(1_500_000)
    assert "." not in formatting.format_size(1_500_000)


def test_a_negative_size_does_not_produce_nonsense():
    assert formatting.format_size(-5) == "0 B"


def test_enormous_sizes_stop_at_the_largest_unit():
    assert formatting.format_size(10 ** 20).endswith(" TB")


# =========================
# Páginas
# =========================

def test_one_page_is_singular():
    assert formatting.format_page_count(1) == "1 página"
    assert formatting.format_page_count(2) == "2 páginas"


# =========================
# Descripciones
# =========================

def test_items_are_described_per_kind():
    assert formatting.describe_items(ExportKind.IMAGES, 12) == "12 imágenes"
    assert formatting.describe_items(ExportKind.PAGES, 3) == "3 páginas PNG"


def test_a_single_item_is_singular():
    assert formatting.describe_items(ExportKind.IMAGES, 1) == "1 imagen"
    assert formatting.describe_items(ExportKind.PAGES, 1) == "1 página PNG"


def test_a_split_describes_no_items():
    """Its product is the file already named next to it; "1 archivo" adds nothing."""
    assert formatting.describe_items(ExportKind.SPLIT, 1) == ""


def test_the_export_summary_joins_items_and_size():
    assert formatting.describe_export(ExportKind.IMAGES, 12, 49_500) == "12 imágenes · 48,3 KB"


def test_a_split_summary_is_only_its_size():
    assert formatting.describe_export(ExportKind.SPLIT, 1, 1_290_000) == "1,2 MB"
