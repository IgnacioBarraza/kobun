"""
The notes generator lives in scripts/, which is not a package: it is loaded by
path so the classification —where it can get things wrong— can be tested.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load_module():
    path = ROOT / "scripts" / "release_notes.py"
    spec = importlib.util.spec_from_file_location("release_notes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


notes = _load_module()


def commit(subject: str, short_hash: str = "abc1234"):
    return notes.parse(short_hash, subject)


# =========================
# Parsing
# =========================


def test_parses_type_and_description():
    result = commit("feat: agrega selector de temas")

    assert result.type == "feat"
    assert result.text == "agrega selector de temas"
    assert result.scope is None
    assert not result.breaking


def test_parses_scope():
    result = commit("fix(ui): corrige el fondo del QLabel")

    assert result.scope == "ui"
    assert result.text == "corrige el fondo del QLabel"


def test_parses_breaking_marker():
    assert commit("feat!: cambia el formato del historial").breaking


def test_uppercase_type_is_normalised():
    """`Refactor:` and `refactor:` are the same type to whoever reads the notes."""
    assert commit("Refactor: mueve AppTheme a shared").type == "refactor"


def test_commit_without_convention_keeps_its_subject():
    result = commit("Update README.md")

    assert result.type == notes.NO_TYPE
    assert result.text == "Update README.md"


# =========================
# Classification
# =========================


def test_sections_follow_the_declared_order():
    body = notes.build_notes(
        [
            commit("chore: sube pytest"),
            commit("fix: corrige el rango"),
            commit("feat: agrega el .deb"),
        ],
        tag="v0.2.0",
        previous="v0.1.0",
    )

    assert body.index("### Features") < body.index("### Bug Fixes") < body.index("### Maintenance")


def test_breaking_goes_first_and_is_not_repeated_in_its_type():
    body = notes.build_notes(
        [commit("feat!: cambia el formato del historial"), commit("feat: agrega el .deb")],
        tag="v0.2.0",
        previous="v0.1.0",
    )

    assert body.index(notes.BREAKING_TITLE) < body.index("### Features")
    assert body.count("Cambia el formato del historial") == 1


def test_unknown_type_does_not_disappear():
    """
    A type in no section is still a change: it gets published under "Other
    Changes" rather than dropping out of the notes unnoticed.
    """
    body = notes.build_notes([commit("wip: algo a medio hacer")], tag="v0.2.0", previous="v0.1.0")

    assert "### Other Changes" in body
    assert "Algo a medio hacer" in body


def test_housekeeping_is_listed_rather_than_hidden():
    """
    "There were no changes" and "the changes were internal" are different
    things, so refactors and CI work get a section of their own instead of
    disappearing.
    """
    body = notes.build_notes(
        [commit("refactor: separa el resolvedor"), commit("ci: agrega la matriz")],
        tag="v0.2.0",
        previous="v0.1.0",
    )

    assert "### Maintenance" in body
    assert "Separa el resolvedor" in body
    assert "Agrega la matriz" in body


def test_documentation_and_tests_get_their_own_sections():
    body = notes.build_notes(
        [commit("docs: explica el release"), commit("test: cubre el rango")],
        tag="v0.2.0",
        previous="v0.1.0",
    )

    assert "### Documentation" in body
    assert "### Tests" in body


def test_does_not_repeat_the_same_change():
    """Rebases and cherry-picks duplicate subjects; in the notes they read badly."""
    body = notes.build_notes(
        [commit("feat: agrega el .deb", "aaa1111"), commit("feat: agrega el .deb", "bbb2222")],
        tag="v0.2.0",
        previous="v0.1.0",
    )

    assert body.count("Agrega el .deb") == 1


def test_scope_is_highlighted_and_the_hash_follows():
    body = notes.build_notes(
        [commit("fix(ui): corrige el fondo", "abc1234")], tag="v0.2.0", previous="v0.1.0"
    )

    assert "* **ui:** Corrige el fondo (abc1234)" in body


def test_the_hash_links_to_the_commit_when_the_repository_is_known():
    """
    A bare hash becomes a link on a release page, but these notes are also
    written to the job summary and read from a terminal, where it is seven
    characters.
    """
    body = notes.build_notes(
        [commit("fix: algo", "abc1234")],
        tag="v0.2.0",
        previous="v0.1.0",
        slug="IgnacioBarraza/kobun",
    )

    assert "([abc1234](https://github.com/IgnacioBarraza/kobun/commit/abc1234))" in body


def test_a_description_reads_as_a_sentence():
    body = notes.build_notes([commit("feat: agrega el .deb")], tag="v0.2.0", previous="v0.1.0")

    assert "Agrega el .deb" in body


def test_an_identifier_is_not_capitalised():
    """
    `pyproject.toml` would become `Pyproject.toml`, and `open_in_default_app`
    would stop naming anything.
    """
    for subject, expected in (
        ("chore: pyproject.toml pasa a 3.10", "pyproject.toml pasa"),
        ("fix: open_in_default_app ya no bloquea", "open_in_default_app ya no"),
        ("fix: `kobun.exe` arranca sin consola", "`kobun.exe` arranca"),
    ):
        body = notes.build_notes([commit(subject)], tag="v0.2.0", previous="v0.1.0")
        assert expected in body


# =========================
# Whole document
# =========================


def test_includes_the_install_instructions():
    body = notes.build_notes([commit("feat: algo")], tag="v0.2.0", previous="v0.1.0")

    assert "## Install" in body
    assert "sudo apt install" in body
    assert "kobun.exe" in body


def test_comparison_link_between_tags():
    body = notes.build_notes(
        [commit("feat: algo")], tag="v0.2.0", previous="v0.1.0", slug="IgnacioBarraza/kobun"
    )

    assert "compare/v0.1.0...v0.2.0" in body


def test_first_release_links_to_the_commit_list():
    body = notes.build_notes(
        [commit("feat: algo")], tag="v0.1.0", previous=None, slug="IgnacioBarraza/kobun"
    )

    assert "commits/v0.1.0" in body
    assert "First published version." in body


def test_no_commits_says_so_instead_of_leaving_the_section_empty():
    body = notes.build_notes([], tag="v0.2.0", previous="v0.1.0")

    assert "No changes recorded since v0.1.0." in body


# =========================
# Versions and prereleases
# =========================


def test_the_tag_version_keeps_the_prerelease_suffix():
    """
    semantic-release writes the suffix into the package, so the comparison is
    exact: a package at `0.2.0` with a `v0.2.0-alpha.1` tag is an error.
    """
    assert notes.version_of_tag("v0.2.0-alpha.1") == "0.2.0-alpha.1"
    assert notes.version_of_tag("0.2.0") == "0.2.0"


def test_recognises_prereleases_by_their_suffix():
    assert notes.is_prerelease("v0.2.0-alpha.1")
    assert not notes.is_prerelease("v0.2.0")


def test_the_release_commit_is_not_a_change():
    """
    `chore(release): v0.2.0` is written by semantic-release when versioning;
    listing it would make every release count its own publication as news.
    """
    assert notes.is_release_commit(commit("chore(release): v0.2.0 [skip ci]"))
    assert not notes.is_release_commit(commit("chore: sube pytest"))


def test_a_prerelease_warns_before_the_install_block():
    body = notes.build_notes([commit("feat: algo")], tag="v0.2.0-alpha.1", previous="v0.1.0")

    assert body.index("Test build") < body.index("## Install")


def test_a_definitive_version_carries_no_warning():
    body = notes.build_notes([commit("feat: algo")], tag="v0.2.0", previous="v0.1.0")

    assert "Test build" not in body


def test_the_tag_has_to_match_the_package_version():
    """
    The version is shown inside the app: if tag and package disagree, what was
    downloaded lies about which version it is.
    """
    notes.check_version(f"v{notes.package_version()}")

    with pytest.raises(SystemExit, match="does not match"):
        notes.check_version("v99.0.0")


def test_a_nonexistent_revision_fails_with_a_message_and_not_a_traceback():
    with pytest.raises(SystemExit, match="does not exist in this repository"):
        notes.check_revision("v999.does-not-exist")
# =========================
# The hand-written summary
# =========================


@pytest.fixture
def highlights_dir(tmp_path):
    """A stand-in for docs/release-notes, so nothing touches the real one."""
    folder = tmp_path / "release-notes"
    folder.mkdir()

    return folder


def write(folder: Path, name: str, body: str) -> Path:
    path = folder / name
    path.write_text(body, encoding="utf-8")

    return path


def test_a_written_summary_is_read_back(highlights_dir):
    source = write(highlights_dir, "next.md", "### Vista previa\n\nLa pantalla muestra la página.")

    assert "Vista previa" in notes.read_highlights(source)


def test_the_guidance_never_reaches_the_release(highlights_dir):
    """
    The instructions for whoever writes the file are long and blunt on purpose,
    and none of it is for whoever reads the release.
    """
    source = write(
        highlights_dir,
        "next.md",
        "<!--\nEscribí dos líneas por cambio.\nNo pongas nombres de archivos.\n-->\n\n### Algo",
    )

    summary = notes.read_highlights(source)

    assert summary == "### Algo"
    assert "Escribí" not in summary


def test_a_file_with_only_guidance_counts_as_empty(highlights_dir):
    """Which is what it is right after a version ships."""
    source = write(highlights_dir, "next.md", "<!--\nplantilla\n-->\n\n   \n")

    assert notes.read_highlights(source) is None


def test_a_missing_file_is_not_an_error(highlights_dir):
    assert notes.read_highlights(highlights_dir / "no-existe.md") is None


def test_an_archived_summary_drops_its_own_title(highlights_dir):
    """
    The archived files carry `# v0.4.0` so they read as documents on their own;
    the release page already says which version it is.
    """
    source = write(highlights_dir, "v0.4.0.md", "# v0.4.0\n\n### Vista previa\n\nTexto.")

    summary = notes.read_highlights(source)

    assert summary.startswith("### Vista previa")


def test_a_heading_that_is_not_the_title_survives(highlights_dir):
    source = write(highlights_dir, "next.md", "### Vista previa\n\nTexto.")

    assert notes.read_highlights(source).startswith("### Vista previa")


# =========================
# Which summary belongs to which tag
# =========================


def test_an_archived_version_reads_its_own_file(highlights_dir, monkeypatch):
    monkeypatch.setattr(notes, "HIGHLIGHTS_DIRECTORY", highlights_dir)
    monkeypatch.setattr(notes, "HIGHLIGHTS_FILE", highlights_dir / "next.md")
    write(highlights_dir, "v0.3.0.md", "# v0.3.0\n\nLo de la 0.3.0.")
    write(highlights_dir, "next.md", "Lo que se está escribiendo.")

    assert notes.highlights_for("v0.3.0") == "Lo de la 0.3.0."


def test_the_version_being_prepared_reads_next(highlights_dir, monkeypatch):
    monkeypatch.setattr(notes, "HIGHLIGHTS_DIRECTORY", highlights_dir)
    monkeypatch.setattr(notes, "HIGHLIGHTS_FILE", highlights_dir / "next.md")
    monkeypatch.setattr(notes, "package_version", lambda: "0.4.0-alpha.1")
    write(highlights_dir, "next.md", "Lo que se está escribiendo.")

    assert notes.highlights_for("v0.4.0-alpha.1") == "Lo que se está escribiendo."


def test_an_old_tag_does_not_pick_up_the_next_version_s_summary(highlights_dir, monkeypatch):
    """
    Regression: regenerating the notes of an old tag published whatever was
    being written for the next version, as if it had shipped back then.
    """
    monkeypatch.setattr(notes, "HIGHLIGHTS_DIRECTORY", highlights_dir)
    monkeypatch.setattr(notes, "HIGHLIGHTS_FILE", highlights_dir / "next.md")
    monkeypatch.setattr(notes, "package_version", lambda: "0.4.0-alpha.1")
    write(highlights_dir, "next.md", "Lo que se está escribiendo.")

    assert notes.highlights_for("v0.3.0") is None


def test_an_alpha_and_its_stable_share_the_summary(highlights_dir, monkeypatch):
    """
    They are the same version being prepared; the alpha shows it in progress and
    the definitive one shows it as the final summary.
    """
    monkeypatch.setattr(notes, "HIGHLIGHTS_DIRECTORY", highlights_dir)
    monkeypatch.setattr(notes, "HIGHLIGHTS_FILE", highlights_dir / "next.md")
    monkeypatch.setattr(notes, "package_version", lambda: "0.4.0")
    write(highlights_dir, "next.md", "Lo mismo.")

    assert notes.highlights_for("v0.4.0-alpha.2") == "Lo mismo."
    assert notes.highlights_for("v0.4.0") == "Lo mismo."


# =========================
# The summary on the page
# =========================


def test_the_summary_opens_the_page(highlights_dir):
    body = notes.build_notes(
        [commit("feat: algo")], tag="v0.4.0", previous="v0.3.0", highlights="### Vista previa"
    )

    assert body.index("What's new in 0.4.0") < body.index("## Install")


def test_a_prerelease_titles_its_summary_as_in_progress(highlights_dir):
    body = notes.build_notes(
        [commit("feat: algo")], tag="v0.4.0-alpha.1", previous="v0.3.0", highlights="### Algo"
    )

    assert "on the way to 0.4.0" in body
    assert "What's new in" not in body


def test_the_prerelease_warning_names_the_version_it_leads_to(highlights_dir):
    body = notes.build_notes([commit("feat: algo")], tag="v0.4.0-alpha.3", previous="v0.3.0")

    assert "Test build on the way to 0.4.0" in body


def test_a_definitive_version_without_a_summary_says_so(highlights_dir):
    """
    A release page with no summary is a mistake, and hiding it would only make
    it repeat.
    """
    body = notes.build_notes([commit("feat: algo")], tag="v0.4.0", previous="v0.3.0")

    assert "No summary was written" in body


def test_a_prerelease_without_a_summary_stays_quiet(highlights_dir):
    """It is a test build, and the warning above already says so."""
    body = notes.build_notes([commit("feat: algo")], tag="v0.4.0-alpha.1", previous="v0.3.0")

    assert "No summary was written" not in body
    assert "on the way to 0.4.0" in body


# =========================
# Where the commit log goes
# =========================


def test_the_commit_log_folds_under_a_summary(highlights_dir):
    """
    Six commits saying "implement page preview" are the record of the work, not
    a description of it, and they should not be the first thing on the page.
    """
    body = notes.build_notes(
        [commit("feat: uno"), commit("fix: dos")],
        tag="v0.4.0",
        previous="v0.3.0",
        highlights="### Vista previa",
    )

    assert "<summary>All changes (2)</summary>" in body
    assert body.index("### Vista previa") < body.index("All changes")


def test_without_a_summary_the_commit_log_is_the_page(highlights_dir):
    body = notes.build_notes([commit("feat: uno")], tag="v0.4.0-alpha.1", previous="v0.3.0")

    assert "### Features" in body
    assert "All changes" not in body


def test_the_log_opens_with_the_version_and_its_date():
    """The shape conventional-changelog writes, which everyone has read before."""
    body = notes.build_notes(
        [commit("feat: uno")],
        tag="v0.3.0",
        previous="v0.2.0",
        slug="IgnacioBarraza/kobun",
    )

    assert "## [0.3.0](https://github.com/IgnacioBarraza/kobun/compare/v0.2.0...v0.3.0)" in body


def test_nothing_folds_twice(highlights_dir):
    """A <details> inside a <details> is two clicks to read one line."""
    body = notes.build_notes(
        [commit("feat: uno"), commit("chore: interno")],
        tag="v0.4.0",
        previous="v0.3.0",
        highlights="### Algo",
    )

    assert body.count("<details>") == 1
    assert "### Maintenance" in body


def test_breaking_changes_never_fold(highlights_dir):
    """
    They are the one thing that can make an update cost someone work, and they
    have to be visible without a click.
    """
    body = notes.build_notes(
        [commit("feat!: cambia todo"), commit("feat: algo")],
        tag="v0.4.0",
        previous="v0.3.0",
        highlights="### Algo",
    )

    assert body.index(notes.BREAKING_TITLE) < body.index("<details>")


def test_a_first_release_still_says_it_is_the_first(highlights_dir):
    body = notes.build_notes(
        [commit("feat: algo")], tag="v0.1.0", previous=None, highlights="### Algo"
    )

    assert "First published version." in body


# =========================
# Filing a published summary
# =========================


def test_archiving_files_the_summary_under_its_version(highlights_dir):
    write(highlights_dir, "next.md", "<!--\nplantilla\n-->\n\n### Vista previa\n\nTexto.")

    assert notes.archive_highlights("v0.4.0", directory=highlights_dir) == 0

    filed = (highlights_dir / "v0.4.0.md").read_text(encoding="utf-8")
    assert filed.startswith("# v0.4.0")
    assert "### Vista previa" in filed


def test_archiving_empties_the_file_but_keeps_the_guidance(highlights_dir):
    """
    The next version starts blank, and whoever writes it still has the rules in
    front of them.
    """
    write(highlights_dir, "next.md", "<!--\nEscribí dos líneas por cambio.\n-->\n\n### Algo")

    notes.archive_highlights("v0.4.0", directory=highlights_dir)

    remaining = (highlights_dir / "next.md").read_text(encoding="utf-8")
    assert notes.read_highlights(highlights_dir / "next.md") is None
    assert "Escribí dos líneas por cambio." in remaining


def test_archiving_nothing_fails_instead_of_writing_an_empty_file(highlights_dir):
    write(highlights_dir, "next.md", "<!--\nplantilla\n-->")

    assert notes.archive_highlights("v0.4.0", directory=highlights_dir) == 1
    assert not (highlights_dir / "v0.4.0.md").exists()


# =========================
# The version a tag leads to
# =========================


@pytest.mark.parametrize(
    "tag, expected",
    [("v0.4.0", "0.4.0"), ("v0.4.0-alpha.1", "0.4.0"), ("0.4.0-rc.2", "0.4.0")],
)
def test_the_base_version_drops_the_prerelease_suffix(tag, expected):
    assert notes.base_version(tag) == expected
