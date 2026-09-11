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

    assert body.index("### New") < body.index("### Fixes") < body.index("Internal")


def test_breaking_goes_first_and_is_not_repeated_in_its_type():
    body = notes.build_notes(
        [commit("feat!: cambia el formato del historial"), commit("feat: agrega el .deb")],
        tag="v0.2.0",
        previous="v0.1.0",
    )

    assert body.index(notes.BREAKING_TITLE) < body.index("### New")
    assert body.count("cambia el formato del historial") == 1


def test_unknown_type_does_not_disappear():
    """
    A type in no section is still a change: it gets published under "Other
    changes" rather than dropping out of the notes unnoticed.
    """
    body = notes.build_notes([commit("wip: algo a medio hacer")], tag="v0.2.0", previous="v0.1.0")

    assert "### Other changes" in body
    assert "algo a medio hacer" in body


def test_internal_changes_are_folded():
    body = notes.build_notes(
        [commit("refactor: separa el resolvedor"), commit("ci: agrega la matriz")],
        tag="v0.2.0",
        previous="v0.1.0",
    )

    assert "<details>" in body
    assert "<summary>Internal (2)</summary>" in body


def test_does_not_repeat_the_same_change():
    """Rebases and cherry-picks duplicate subjects; in the notes they read badly."""
    body = notes.build_notes(
        [commit("feat: agrega el .deb", "aaa1111"), commit("feat: agrega el .deb", "bbb2222")],
        tag="v0.2.0",
        previous="v0.1.0",
    )

    assert body.count("agrega el .deb") == 1


def test_scope_is_highlighted_and_the_hash_follows():
    body = notes.build_notes(
        [commit("fix(ui): corrige el fondo", "abc1234")], tag="v0.2.0", previous="v0.1.0"
    )

    assert "- **ui**: corrige el fondo (abc1234)" in body


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
