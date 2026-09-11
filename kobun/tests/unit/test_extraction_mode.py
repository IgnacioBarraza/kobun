import pytest

from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode


def test_modes_round_trip_through_their_string_value():
    """A Qt combo box hands the data back as plain text, and so does the JSON."""
    assert ExtractionMode("embedded_images") is ExtractionMode.EMBEDDED_IMAGES
    assert ExtractionMode("page_raster") is ExtractionMode.PAGE_RASTER


def test_an_unknown_value_is_rejected():
    with pytest.raises(ValueError):
        ExtractionMode("tablas")


def test_only_the_raster_mode_produces_one_file_per_page():
    assert ExtractionMode.PAGE_RASTER.produces_one_file_per_page is True
    assert ExtractionMode.EMBEDDED_IMAGES.produces_one_file_per_page is False
