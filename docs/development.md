# Development

Everything needed to run Kobun from source, test it, and build the artifacts
that get published. For how versions and releases are decided, see
[releasing.md](releasing.md).

## Setup

- Python **3.10+**
- pip

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

That installs the project in editable mode with its development extras.
`requirements.txt` only points at `pyproject.toml`, which is the single source
of truth for dependencies. Three extras exist:

| Extra | For | Brings |
|---|---|---|
| `dev` | running the tests | pytest |
| `build` | producing the executables | PyInstaller |
| `release` | versioning and publishing (CI uses it) | python-semantic-release |

## Running

```bash
kobun                        # if the project is installed
./.venv/bin/python main.py   # straight from the source tree
```

Both accept a PDF as an argument, which is also how the desktop passes the file
when Kobun is chosen from "Open with".

### Desktop integration on Linux (optional)

On Wayland the compositor does not read the icon from the window: it matches the
application to a `.desktop` file through its app id. Without that file the dock
shows a generic Python icon.

```bash
./.venv/bin/python scripts/install_desktop_entry.py
```

This installs the icons into `~/.local/share/icons/hicolor` and the entry into
`~/.local/share/applications`, with no root required. Kobun then appears in the
application menu too. Use `--uninstall` to undo it.

## Tests

```bash
pytest                        # everything (testpaths is configured)
pytest kobun/tests/unit       # pure domain, no dependencies
```

The `unit/` suite runs with nothing but pytest installed — that invariant is
verified in CI, because it is what proves the domain does not depend on the
framework. The `integration/` suite generates real PDFs with PyMuPDF and drives
the real Qt window in offscreen mode, checking that exactly the requested pages
come out; it skips itself when PyMuPDF or PySide6 are missing.

Some of the suite verifies properties rather than cases: every theme's contrast
against WCAG AA, that palettes of the same group are visually distinguishable,
and that the icon files carry an alpha channel and every declared size.

## Conventions

**Language.** Code, comments, docstrings and documentation are in English. The
**interface is in Spanish** — window labels, status messages, the error text the
user reads, and the `Comment=` of the desktop entry. Domain exception messages
count as interface: `error_messages.translate()` shows them to the user
verbatim, so they stay in Spanish even inside `domain/`.

**Commits** follow [Conventional Commits](https://www.conventionalcommits.org/),
and they are not decoration: the version is derived from them. A commit without
a `type:` prefix publishes nothing. See
[releasing.md](releasing.md#what-the-commits-decide).

**Layers.** The domain knows neither Qt nor PyMuPDF. Page indices are 1-based
everywhere; the translation to PyMuPDF's 0-based API happens only inside
`PdfEngineAdapter`. The window talks to a viewmodel, and the viewmodel is the
only thing that touches the application layer.

## Building an executable

```bash
pip install -e .[build]
python scripts/build_app.py            # single file, easiest to distribute
python scripts/build_app.py --onedir   # a folder, starts faster
```

The recipe lives in [`packaging/kobun.spec`](../packaging/kobun.spec) and is
shared by both platforms. **PyInstaller does not cross-compile**: the Linux
binary must be built on Linux and the Windows `.exe` on Windows (or in CI).

A build that succeeds is not a build that works — a Qt module excluded too
aggressively only fails at startup. Always launch the result before shipping it.

| | Linux | Windows |
|---|---|---|
| Output | `dist/kobun` | `dist/kobun.exe` |
| Size | ~93 MB (one file) | similar |
| Installer | `.deb` (below) | Inno Setup (below) |
| Icon | resolved by the desktop from the `.desktop` entry | embedded in the `.exe` |
| Console window | n/a | none (`console=False`) |

Released files are named `kobun`, `kobun.exe` and `kobun_<version>_amd64.deb`.
The version is not in the first two names because the app shows it in its own
sidebar; the `.deb` keeps the Debian convention because tooling expects it.

On Linux, point the desktop entry at the built binary instead of the development
environment:

```bash
python scripts/install_desktop_entry.py --exec dist/kobun
```

### Linux package

A bare executable is not a usable distribution format on Linux: modern file
managers refuse to launch binaries on double-click, and downloading one loses
its executable bit. The `.deb` is the Linux counterpart of the Windows
installer — it puts the binary in `/usr/bin`, registers the `.desktop` entry and
the icons, and shows up in the application menu.

```bash
python scripts/build_app.py
python scripts/build_deb.py
sudo apt install ./dist/kobun_*_amd64.deb
```

Its dependencies were not guessed: they come from walking the `NEEDED` entries
of every library in the Qt bundle and mapping what is missing to packages.

### Windows installer

The `.exe` is **portable**: it runs on double-click, with no installation. What
it does not give you is a Start menu shortcut, a PDF association or an entry in
Add/Remove Programs. That is what [`packaging/kobun.iss`](../packaging/kobun.iss)
adds, via Inno Setup:

```bat
python scripts\build_app.py
iscc packaging\kobun.iss
```

It installs per-user, so no UAC prompt, and it registers Kobun as an *option*
for PDFs rather than stealing the default association from whatever viewer is
already installed.

Note that an unsigned executable downloaded from the internet triggers a
SmartScreen warning on first run. Removing it requires a code-signing
certificate.

## What CI is made of

Split by responsibility, so that a change to one concern touches one file:

| File | Responsibility |
|---|---|
| [`workflows/ci.yml`](../.github/workflows/ci.yml) | is the code healthy? Tests + a build that proves the binary still comes out |
| [`workflows/release.yml`](../.github/workflows/release.yml) | publish: version, changelog, release, binaries attached, back-merge |
| [`workflows/tests.yml`](../.github/workflows/tests.yml) | the suite itself, called by both — one definition, so what runs before a release is what ran on the PR |
| [`actions/python-env`](../.github/actions/python-env/action.yml) | Python, Qt's system libraries, the project installed |
| [`actions/build-app`](../.github/actions/build-app/action.yml) | the binary, the `.deb`, and the size check that catches a build missing its dependencies |

Pushes to `main` and `develop` are deliberately excluded from `ci.yml`:
`release.yml` calls the same test suite before versioning, so including them
would run everything twice per merge. A pull request into `develop` does run
`ci.yml` — `branches-ignore` filters the push event only.

The two composite actions exist because their steps were repeated across jobs —
installing Qt's libraries appeared three times, building appeared twice. Adding
a system library is now one edit rather than a hunt.

Artifacts from `ci.yml` let you try a branch's build without releasing anything;
they live for 30 days.
