import pytest

from kobun.domain.pdf.exceptions.invalid_extraction_exception import InvalidExtractionException
from kobun.domain.pdf.exceptions.invalid_page_range_exception import InvalidPageRangeException
from kobun.domain.pdf.exceptions.invalid_pdf_exception import InvalidPdfException
from kobun.domain.pdf.services.asset_extractor_service import (
    DEFAULT_DPI,
    MAX_DPI,
    MIN_DPI,
    MIN_IMAGE_SIDE,
    AssetExtractorService,
)
from kobun.domain.pdf.value_objects.asset_origin import AssetOrigin
from kobun.domain.pdf.value_objects.extraction_mode import ExtractionMode
from kobun.domain.pdf.value_objects.page_selection import PageSelection

FIGURES = ExtractionMode.FIGURES
IMAGES = ExtractionMode.EMBEDDED_IMAGES
RASTER = ExtractionMode.PAGE_RASTER

EMBEDDED = AssetOrigin.EMBEDDED
FIGURE = AssetOrigin.FIGURE
PAGE = AssetOrigin.PAGE


@pytest.fixture
def service():
    return AssetExtractorService()


# =========================
# Validación
# =========================

def test_a_selection_inside_the_document_is_accepted(service, make_pdf_document):
    document = make_pdf_document(page_count=20)

    service.validate_request(document, PageSelection.parse("1-5,18"), IMAGES, DEFAULT_DPI)


def test_a_selection_past_the_last_page_is_rejected(service, make_pdf_document):
    document = make_pdf_document(page_count=10)

    with pytest.raises(InvalidPageRangeException, match="fuera de límites"):
        service.validate_request(document, PageSelection.parse("8-14"), IMAGES, DEFAULT_DPI)


def test_a_document_without_pages_is_rejected(service, make_pdf_document):
    document = make_pdf_document(page_count=0)

    with pytest.raises(InvalidPdfException):
        service.validate_request(document, PageSelection.parse("1"), IMAGES, DEFAULT_DPI)


def test_a_missing_file_is_rejected(service, make_pdf_document):
    document = make_pdf_document()
    document.storage_path.unlink()

    with pytest.raises(InvalidPdfException, match="no existe"):
        service.validate_request(document, PageSelection.parse("1"), IMAGES, DEFAULT_DPI)


def test_the_resolution_is_validated_even_in_the_mode_that_ignores_it(service, make_pdf_document):
    """
    A nonsense value that silently does nothing in one mode and breaks in the
    other is worse than a consistent error.
    """
    document = make_pdf_document(page_count=10)

    with pytest.raises(InvalidExtractionException):
        service.validate_request(document, PageSelection.parse("1"), IMAGES, 5000)


# =========================
# Resolución
# =========================

def test_the_usable_resolution_range_is_accepted(service):
    service.validate_dpi(MIN_DPI)
    service.validate_dpi(DEFAULT_DPI)
    service.validate_dpi(MAX_DPI)


@pytest.mark.parametrize("dpi", [0, -100, MIN_DPI - 1, MAX_DPI + 1])
def test_a_resolution_out_of_range_is_rejected(service, dpi):
    with pytest.raises(InvalidExtractionException, match="entre"):
        service.validate_dpi(dpi)


@pytest.mark.parametrize("dpi", ["150", 150.5, None, True])
def test_a_resolution_that_is_not_a_whole_number_is_rejected(service, dpi):
    """
    `True` is in the list on purpose: it is an int for Python, and a boolean
    arriving here means someone wired a checkbox to the wrong field.
    """
    with pytest.raises(InvalidExtractionException, match="entero"):
        service.validate_dpi(dpi)


# =========================
# Qué vale la pena guardar
# =========================

def test_an_image_of_a_usable_size_is_kept(service):
    assert service.is_significant_image(200, 150) is True
    assert service.is_significant_image(MIN_IMAGE_SIDE, MIN_IMAGE_SIDE) is True


def test_slivers_and_spacers_are_dropped(service):
    """
    PDFs are full of 1x1 spacers and hairline rules stored as images. Handing
    the user 300 files of which 280 are invisible makes the feature useless.
    """
    assert service.is_significant_image(1, 1) is False
    assert service.is_significant_image(2000, 3) is False
    assert service.is_significant_image(3, 2000) is False


def test_unknown_dimensions_count_as_insignificant(service):
    """The engine reports zero when it cannot tell; nothing is claimed about it."""
    assert service.is_significant_image(0, 0) is False


# =========================
# Nombre de la carpeta
# =========================

def test_the_folder_name_carries_the_source_and_the_mode(service, make_pdf_document):
    document = make_pdf_document(filename="libro.pdf")

    assert service.suggest_output_directory_name(document, FIGURES) == "libro_figuras"
    assert service.suggest_output_directory_name(document, IMAGES) == "libro_imagenes"
    assert service.suggest_output_directory_name(document, RASTER) == "libro_paginas"


def test_the_folder_name_does_not_depend_on_the_selection(service, make_pdf_document):
    """
    So extracting pages 1-5 and then 6-10 suggests the same folder both times and
    everything ends up together. It used to carry the selection, which produced a
    folder per run.
    """
    document = make_pdf_document(filename="libro.pdf")

    first = service.suggest_output_directory_name(document, FIGURES)
    second = service.suggest_output_directory_name(document, FIGURES)

    assert first == second == "libro_figuras"


def test_the_folder_name_is_safe_for_windows(service, make_pdf_document):
    document = make_pdf_document(filename='rep<or>t:"1".pdf')

    name = service.suggest_output_directory_name(document, FIGURES)

    assert not set(name) & set('<>:"/\\|?*')


def test_illegal_characters_become_underscores_rather_than_a_fallback(service, make_pdf_document):
    document = make_pdf_document(filename='<>:".pdf')

    assert service.suggest_output_directory_name(document, IMAGES) == "_____imagenes"


def test_a_source_name_that_sanitises_to_nothing_falls_back(service, make_pdf_document):
    document = make_pdf_document(filename=" .pdf")

    assert service.suggest_output_directory_name(document, IMAGES) == "kobun_imagenes"


def test_the_fallback_does_not_borrow_the_splitter_s_name(service, make_pdf_document):
    """"kobun_split_imagenes" would describe an operation that never happened."""
    document = make_pdf_document(filename=" .pdf")

    assert "split" not in service.asset_filename(document, 1, 1, "png", PAGE)


# =========================
# Nombre de cada archivo
# =========================

def test_a_stored_image_is_named_after_page_and_position(service, make_pdf_document):
    document = make_pdf_document(filename="libro.pdf")

    assert service.asset_filename(document, 7, 2, "png", EMBEDDED) == "libro_p007_img02.png"


def test_a_rendered_figure_is_named_apart_from_a_stored_image(service, make_pdf_document):
    """
    One mode returns both, and a folder where they are indistinguishable hides
    which files are the originals.
    """
    document = make_pdf_document(filename="libro.pdf")

    assert service.asset_filename(document, 7, 1, "png", FIGURE) == "libro_p007_fig01.png"


def test_a_rendered_page_has_no_position_in_its_name(service, make_pdf_document):
    """One file per page, so numbering it within the page would say nothing."""
    document = make_pdf_document(filename="libro.pdf")

    assert service.asset_filename(document, 7, 1, "png", PAGE) == "libro_p007.png"


def test_page_numbers_are_padded_so_the_folder_sorts_correctly(service, make_pdf_document):
    """Without padding, page 10 sorts before page 2 and the folder is unreadable."""
    document = make_pdf_document(filename="libro.pdf")

    names = [service.asset_filename(document, page, 1, "png", PAGE) for page in (2, 10, 100)]

    assert names == ["libro_p002.png", "libro_p010.png", "libro_p100.png"]
    assert sorted(names) == names


def test_a_page_past_three_digits_still_gets_a_full_name(service, make_pdf_document):
    document = make_pdf_document(filename="libro.pdf")

    assert service.asset_filename(document, 1234, 1, "png", PAGE) == "libro_p1234.png"


@pytest.mark.parametrize("extension", ["png", ".png", "PNG", " png "])
def test_the_extension_is_normalised(service, make_pdf_document, extension):
    document = make_pdf_document(filename="libro.pdf")

    assert service.asset_filename(document, 1, 1, extension, PAGE) == "libro_p001.png"


def test_the_original_format_is_preserved(service, make_pdf_document):
    """A stored JPEG comes out as a JPEG; the name must not claim it is PNG."""
    document = make_pdf_document(filename="libro.pdf")

    assert service.asset_filename(document, 1, 1, "jpeg", EMBEDDED) == "libro_p001_img01.jpeg"


def test_an_unusable_extension_does_not_produce_a_broken_name(service, make_pdf_document):
    document = make_pdf_document(filename="libro.pdf")

    assert service.asset_filename(document, 1, 1, "", EMBEDDED) == "libro_p001_img01.bin"
