#!/usr/bin/env python3
"""
Packages the Linux executable into an installable .deb.

    ./.venv/bin/python scripts/build_app.py
    ./.venv/bin/python scripts/build_deb.py

This is the counterpart of the Windows installer: a bare executable is not
enough on modern Linux, because file managers no longer launch binaries on
double click —GNOME disabled it for security— so it has to be installed with
its .desktop entry to show up in the application menu.

The result lands in dist/kobun_<version>_amd64.deb and installs with:

    sudo apt install ./dist/kobun_<version>_amd64.deb
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import kobun  # noqa: E402
from kobun.shared.config.app_settings import APP_ICON_SIZES, APP_ID, APP_NAME, app_icon_file  # noqa: E402

ARCHITECTURE = "amd64"
MAINTAINER = "Ignacio Barraza <ignacio.barraza.rioja@gmail.com>"

# Measured, not guessed: these are the libraries the .so files in the Qt bundle
# need and that the bundle itself does not carry. They come from walking the
# NEEDED entries of every packaged library and mapping them to packages with
# dpkg -S.
DEPENDENCIES = [
    "libc6",
    "libdrm2",
    "libegl1",
    "libgl1",
    "libwayland-client0",
    "libwayland-cursor0",
    "libwayland-egl1",
    "libxcb1",
]

# Debian policy keeps package descriptions in English; the desktop entry below
# is the part the user reads in their application menu, and that stays in the
# language of the interface.
DESCRIPTION = """Desktop utility to split PDFs by page ranges
 Kobun extracts page ranges from a PDF —discontinuous ones too, such as
 1-5,10-15,20— into a new file, without touching the original.
 .
 It includes an export history and ten visual themes."""

CONTROL = """Package: {package}
Version: {version}
Section: utils
Priority: optional
Architecture: {architecture}
Depends: {dependencies}
Installed-Size: {size}
Maintainer: {maintainer}
Homepage: https://github.com/IgnacioBarraza/kobun
Description: {description}
"""

DESKTOP = """[Desktop Entry]
Type=Application
Version=1.0
Name={name}
GenericName=Divisor de PDFs
Comment=Extraer rangos de páginas de un PDF a un archivo nuevo
Exec=/usr/bin/{app_id} %f
Icon={app_id}
Terminal=false
Categories=Office;
MimeType=application/pdf;
StartupWMClass={app_id}
StartupNotify=true
"""

# The desktop caches do not refresh on their own: without this the icon may not
# show up until the next login.
POSTINST = """#!/bin/sh
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
"""

POSTRM = POSTINST


def prepare_tree(destination: Path, binary: Path) -> None:
    (destination / "DEBIAN").mkdir(parents=True)
    bin_dir = destination / "usr" / "bin"
    bin_dir.mkdir(parents=True)

    executable = bin_dir / APP_ID
    shutil.copy2(binary, executable)
    executable.chmod(0o755)

    apps = destination / "usr" / "share" / "applications"
    apps.mkdir(parents=True)
    entry = apps / f"{APP_ID}.desktop"
    entry.write_text(DESKTOP.format(name=APP_NAME, app_id=APP_ID), encoding="utf-8")
    # Debian policy asks for 644 on data files; the build environment's umask
    # can leave them with group write permission.
    entry.chmod(0o644)

    for side in APP_ICON_SIZES:
        source = app_icon_file(side)
        if not source.is_file():
            continue
        folder = destination / "usr" / "share" / "icons" / "hicolor" / f"{side}x{side}" / "apps"
        folder.mkdir(parents=True, exist_ok=True)
        icon = folder / f"{APP_ID}.png"
        shutil.copy2(source, icon)
        icon.chmod(0o644)

    # Debian policy makes the licence mandatory.
    doc = destination / "usr" / "share" / "doc" / APP_ID
    doc.mkdir(parents=True)
    licence = doc / "copyright"
    shutil.copy2(ROOT / "LICENSE", licence)
    licence.chmod(0o644)


def write_control(destination: Path) -> None:
    kb = sum(f.stat().st_size for f in destination.rglob("*") if f.is_file()) // 1024

    (destination / "DEBIAN" / "control").write_text(
        CONTROL.format(
            package=APP_ID,
            version=kobun.__version__,
            architecture=ARCHITECTURE,
            dependencies=", ".join(DEPENDENCIES),
            size=kb,
            maintainer=MAINTAINER,
            description=DESCRIPTION,
        ),
        encoding="utf-8",
    )

    for name, contents in (("postinst", POSTINST), ("postrm", POSTRM)):
        script = destination / "DEBIAN" / name
        script.write_text(contents, encoding="utf-8")
        script.chmod(0o755)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--binary", type=Path, default=ROOT / "dist" / "kobun",
        help="Executable to package (defaults to dist/kobun)",
    )
    args = parser.parse_args()

    if sys.platform.startswith("win"):
        raise SystemExit("A .deb only makes sense on Linux.")

    if shutil.which("dpkg-deb") is None:
        raise SystemExit("dpkg-deb is missing. Install it with: sudo apt install dpkg-dev")

    binary = args.binary
    if binary.is_dir():
        binary = binary / "kobun"

    if not binary.is_file():
        raise SystemExit(
            f"No executable found at {binary}.\n"
            "Build it first with: python scripts/build_app.py"
        )

    work_dir = ROOT / "build" / "deb"
    if work_dir.exists():
        shutil.rmtree(work_dir)

    prepare_tree(work_dir, binary)
    write_control(work_dir)

    output = ROOT / "dist" / f"{APP_ID}_{kobun.__version__}_{ARCHITECTURE}.deb"
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(work_dir), str(output)],
                   check=True)

    print(f"\nPackage: {output}  ({output.stat().st_size / 1024 / 1024:.0f} MB)")
    print(f"Install:   sudo apt install {output}")
    print(f"Uninstall: sudo apt remove {APP_ID}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
