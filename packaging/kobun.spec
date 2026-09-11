# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller recipe for Kobun, shared by Linux and Windows.

Build it with:

    python scripts/build_app.py

PyInstaller **does not cross-compile**: this file serves both systems, but each
binary has to be produced on the system it targets.
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent  # noqa: F821 — PyInstaller injects SPECPATH
IS_WINDOWS = sys.platform.startswith("win")

# The --onedir command line flag never reaches a .spec file: the recipe decides
# the mode by having a COLLECT step or not. It is read from the environment so
# scripts/build_app.py can choose.
ONE_FILE = os.environ.get("KOBUN_ONEFILE", "1") != "0"

# Themes, icons and the combo box arrows are not .py, so without collecting
# them the executable starts with no colours. And since ThemeService lets the
# exception through when the default theme fails, it does not start at all.
DATA = collect_data_files("kobun.shared")

# Qt ships far more than we use. Every exclusion is verified by running the
# binary: trimming too much breaks at runtime, not at build time.
UNUSED_QT = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
]

EXCLUDED = UNUSED_QT + [
    "tkinter",
    "pytest",
    "setuptools",
    "pip",
]

analysis = Analysis(  # noqa: F821
    [str(ROOT / "main.py")],
    # Pointing at the source tree is required: with the project installed in
    # editable mode PyInstaller sees the package as importable but cannot find
    # the files to bundle, and fails with "No module named kobun.…".
    pathex=[str(ROOT)],
    binaries=[],
    datas=DATA,
    hiddenimports=[],
    hookspath=[],
    excludes=EXCLUDED,
    noarchive=False,
)

pyz = PYZ(analysis.pure)  # noqa: F821

COMMON = dict(
    name="kobun",
    debug=False,
    strip=False,
    upx=False,
    # No console: this is a windowed app. On Windows it avoids the black
    # terminal that would show up behind it.
    console=False,
    # PyInstaller only uses the icon on Windows and macOS; on Linux the desktop
    # resolves it from the .desktop entry.
    icon=str(ROOT / "kobun" / "shared" / "icons" / "kobun.ico") if IS_WINDOWS else None,
)

if ONE_FILE:
    exe = EXE(pyz, analysis.scripts, analysis.binaries, analysis.datas, **COMMON)  # noqa: F821
else:
    # In directory mode the executable stays small and the dependencies sit
    # beside it: it starts faster because nothing is unpacked on every run.
    exe = EXE(pyz, analysis.scripts, exclude_binaries=True, **COMMON)  # noqa: F821
    collection = COLLECT(  # noqa: F821
        exe, analysis.binaries, analysis.datas, strip=False, upx=False, name="kobun",
    )
