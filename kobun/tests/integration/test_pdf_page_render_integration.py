"""
Page rendering over real PDFs.

Where the unit tests check the orchestration with a scripted renderer, these
check the part only PyMuPDF can answer: that a page comes out at the width it
was asked for whatever shape the page is, and that the bytes are a real PNG.
Skipped if PyMuPDF is missing.
"""
import struct

import pytest

pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF no instalado")

from kobun.application.use_cases.render_page_preview_use_case import (  # noqa: E402
    RenderPagePreviewUseCase,
)
from kobun.domain.pdf.exceptions.encrypted_pdf_exception import (  # noqa: E402
    EncryptedPdfException,
)
from kobun.domain.pdf.exceptions.invalid_pdf_exception import InvalidPdfException  # noqa: E402
from kobun.domain.pdf.services.pdf_splitter_service import PdfSplitterService  # noqa: E402
from kobun.application.use_cases.load_pdf_use_case import LoadPdfUseCase  # noqa: E402
from kobun.infrastructure.pdf_engine.pdf_document_opener import PdfDocumentOpener  # noqa: E402
from kobun.infrastructure.pdf_engine.pdf_engine_adapter import PdfEngineAdapter  # noqa: E402
from kobun.infrastructure.repositories.pdf_page_renderer_impl import (  # noqa: E402
    PyMuPdfPageRenderer,
)
from kobun.infrastructure.repositories.pdf_repository_impl import PyMuPdfRepository  # noqa: E402

A4 = (595, 842)
LANDSCAPE = (842, 595)
SQUARE = (500, 500)


def png_dimensions(data: bytes) -> tuple:
    """Width and height straight out of the IHDR, so no image library is needed."""
    return struct.unpack(">II", data[16:24])


@pytest.fixture
def engine_parts():
    engine = PdfEngineAdapter()
    opener = PdfDocumentOpener(engine)

    return engine, opener


@pytest.fixture
def use_case(engine_parts):
    engine, opener = engine_parts

    return RenderPagePreviewUseCase(
        PyMuPdfRepository(engine, opener), PyMuPdfPageRenderer(engine, opener)
    )


@pytest.fixture
def loader(engine_parts):
    engine, opener = engine_parts

    return LoadPdfUseCase(PyMuPdfRepository(engine, opener), PdfSplitterService())


@pytest.fixture
def make_pdf(tmp_path):
    def _make(name: str = "libro.pdf", pages: int = 6, size=A4):
        path = tmp_path / name
        doc = pymupdf.open()

        for number in range(1, pages + 1):
            page = doc.new_page(width=size[0], height=size[1])
            page.insert_text((60, 90), f"PAGINA {number}", fontsize=28)
            page.draw_rect(
                pymupdf.Rect(60, 140, size[0] - 60, size[1] - 140),
                color=(0, 0, 0.8),
            )

        doc.save(path)
        doc.close()

        return path

    return _make


# =========================
# Tamaño
# =========================

def test_a_page_comes_out_at_the_requested_width(use_case, loader, make_pdf):
    document = loader.execute(make_pdf())

    preview = use_case.execute(document, 1, target_width=300)

    assert preview.width == 300
    assert png_dimensions(preview.data) == (300, preview.height)


def test_the_page_s_proportions_are_preserved(use_case, loader, make_pdf):
    document = loader.execute(make_pdf())

    preview = use_case.execute(document, 1, target_width=300)

    assert preview.height == pytest.approx(300 * A4[1] / A4[0], abs=2)


def test_a_landscape_page_comes_back_wide(use_case, loader, make_pdf):
    """
    Sized by width and not by resolution precisely so this works: the same dpi
    would give a landscape page a different width than a portrait one.
    """
    document = loader.execute(make_pdf(name="apaisado.pdf", size=LANDSCAPE))

    preview = use_case.execute(document, 1, target_width=300)

    assert preview.width == 300
    assert preview.height < preview.width
    assert preview.aspect_ratio > 1


def test_a_square_page_comes_back_square(use_case, loader, make_pdf):
    document = loader.execute(make_pdf(name="cuadrado.pdf", size=SQUARE))

    preview = use_case.execute(document, 1, target_width=240)

    assert (preview.width, preview.height) == (240, 240)


def test_a_wider_request_gives_a_bigger_image(use_case, loader, make_pdf):
    document = loader.execute(make_pdf())

    small = use_case.execute(document, 1, target_width=120)
    large = use_case.execute(document, 1, target_width=480)

    assert large.width > small.width
    assert large.size_bytes > small.size_bytes


# =========================
# Contenido
# =========================

def test_the_bytes_are_a_real_png(use_case, loader, make_pdf):
    document = loader.execute(make_pdf())

    preview = use_case.execute(document, 1)

    assert preview.data.startswith(b"\x89PNG\r\n\x1a\n")
    assert preview.size_bytes > 0


def test_different_pages_render_differently(use_case, loader, make_pdf):
    """Each page says its own number, so identical bytes would mean the page
    index is being ignored."""
    document = loader.execute(make_pdf())

    assert use_case.execute(document, 1).data != use_case.execute(document, 4).data


def test_every_page_of_the_document_can_be_rendered(use_case, loader, make_pdf):
    document = loader.execute(make_pdf(pages=8))

    for page in range(1, 9):
        assert use_case.execute(document, page, target_width=120).size_bytes > 0


# =========================
# El PDF de origen
# =========================

def test_the_source_is_left_untouched(use_case, loader, make_pdf):
    path = make_pdf()
    document = loader.execute(path)
    before = path.read_bytes()

    for page in range(1, 7):
        use_case.execute(document, page, target_width=200)

    assert path.read_bytes() == before


def test_the_same_page_can_be_rendered_repeatedly(use_case, loader, make_pdf):
    """
    The document is opened and closed around each render; a leaked handle would
    fail here on Windows and leave the file locked.
    """
    document = loader.execute(make_pdf())

    first = use_case.execute(document, 2, target_width=200)
    second = use_case.execute(document, 2, target_width=200)

    assert first.data == second.data


def test_a_file_that_disappeared_is_reported(use_case, loader, make_pdf):
    path = make_pdf()
    document = loader.execute(path)
    path.unlink()

    with pytest.raises(InvalidPdfException):
        use_case.execute(document, 1)


def test_an_encrypted_pdf_is_rejected_like_everywhere_else(use_case, loader, tmp_path):
    path = tmp_path / "protegido.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="d", user_pw="s")
    doc.close()

    with pytest.raises(EncryptedPdfException):
        loader.execute(path)
