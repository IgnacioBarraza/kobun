"""
Verifica los archivos del icono sin depender de Qt ni de PyMuPDF: son datos
que viajan con el paquete y deben existir aunque la suite corra pelada.
"""
import struct

import pytest

from kobun.shared.config.app_settings import (
    APP_ICON_SIZES,
    ICONS_DIRECTORY,
    WINDOWS_ICON_FILE,
    app_icon_file,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def read_png_header(path):
    """
    Width, height and colour type from the IHDR header, with no libraries.
    Type 6 is RGBA.
    """
    data = path.read_bytes()

    assert data[:8] == PNG_MAGIC, f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    colour_type = data[25]

    return width, height, colour_type


def test_the_icons_directory_ships_with_the_package():
    assert ICONS_DIRECTORY.is_dir()
    assert ICONS_DIRECTORY.is_absolute(), "debe resolverse relativo al paquete"


@pytest.mark.parametrize("size", APP_ICON_SIZES)
def test_every_declared_size_exists(size):
    assert app_icon_file(size).is_file(), f"falta el icono de {size}px"


@pytest.mark.parametrize("size", APP_ICON_SIZES)
def test_every_icon_is_square_and_matches_its_name(size):
    width, height, _ = read_png_header(app_icon_file(size))

    assert (width, height) == (size, size)


@pytest.mark.parametrize("size", APP_ICON_SIZES)
def test_every_icon_has_transparency(size):
    """
    Regression: the original artwork carried solid black corners, so the icon
    showed a black frame around the rounded square.
    """
    _, _, colour_type = read_png_header(app_icon_file(size))

    assert colour_type == 6, f"the {size}px icon has no alpha channel"


def test_the_small_sizes_stay_light():
    """
    The small sizes are always loaded; one weighing hundreds of KB would be a
    sign that a large PNG was saved under another name.
    """
    for size in (16, 24, 32, 48):
        weight = app_icon_file(size).stat().st_size
        assert weight < 20_000, f"the {size}px icon weighs {weight} bytes"


def test_the_windows_icon_bundles_every_size():
    """
    El .ico es un contenedor: cabecera de 6 bytes y una entrada de 16 por
    imagen. Se valida el conteo declarado, no el contenido.
    """
    data = WINDOWS_ICON_FILE.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])

    assert reserved == 0
    assert kind == 1, "type 1 is an icon; 2 would be a cursor"
    assert count == len(APP_ICON_SIZES)


def test_the_windows_icon_entries_point_inside_the_file():
    data = WINDOWS_ICON_FILE.read_bytes()
    count = struct.unpack("<H", data[4:6])[0]

    for i in range(count):
        base = 6 + i * 16
        size, offset = struct.unpack("<II", data[base + 8:base + 16])

        assert size > 0
        assert offset + size <= len(data), f"la entrada {i} apunta fuera del archivo"


def test_the_app_id_is_a_valid_desktop_file_name():
    """
    El app_id tiene que servir como nombre de archivo .desktop: en Wayland es
    lo que permite al compositor encontrar el icono de la app.
    """
    from kobun.shared.config.app_settings import APP_ID

    assert APP_ID
    assert APP_ID == APP_ID.lower()
    assert " " not in APP_ID
    assert APP_ID.isascii()
    assert not APP_ID.endswith(".desktop"), "Qt appends the extension on its own"


def test_the_windows_installer_version_matches_the_package():
    """
    The installer declares its version in its own file. Without this check,
    publishing a setup labelled with an old version goes unnoticed until a user
    installs it.
    """
    import re
    from pathlib import Path

    import kobun

    iss = Path(__file__).resolve().parents[3] / "packaging" / "kobun.iss"
    if not iss.is_file():
        import pytest as _pytest
        _pytest.skip("no hay receta de instalador")

    declarada = re.search(r'#define MyAppVersion "([^"]+)"', iss.read_text(encoding="utf-8"))

    assert declarada is not None, "el .iss debe declarar MyAppVersion"
    assert declarada.group(1) == kobun.__version__


def test_the_windows_installer_points_at_the_bundled_icon():
    """El .ico tiene que existir en el repo: el instalador lo usa como su icono."""
    from pathlib import Path

    import kobun

    root = Path(kobun.__file__).resolve().parent.parent
    assert (root / "kobun" / "shared" / "icons" / "kobun.ico").is_file()
