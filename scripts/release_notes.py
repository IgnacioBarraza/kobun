#!/usr/bin/env python3
"""
Write the notes of a release from the commits since the previous tag.

    python3 scripts/release_notes.py v0.2.0
    python3 scripts/release_notes.py v0.2.0 --output notes.md

Commits in this project follow the `type: description` convention, so the
sections can build themselves and the only hand-written part is the install
block, which does not depend on the changes.

These notes are the shop window of a release — what someone landing on the page
to download the app reads. The historical record is written by semantic-release
into docs/changelog.md. That is why the two formats differ: one groups for
reading, the other archives.

No dependencies: this has to run on the release runner without installing the
project.
"""
import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent

# Unit separator: unlike any printable character, it cannot show up in a commit
# subject.
FIELD_SEPARATOR = "\x1f"

# Marker for commits that do not follow the convention.
NO_TYPE = "*"

OTHER = "Other changes"

# Changes that say nothing to someone who just wants to use the app: published,
# but folded away.
INTERNAL_TYPES = (
    "refactor",
    "chore",
    "docs",
    "doc",
    "test",
    "tests",
    "build",
    "ci",
    "style",
    "revert",
)

# (title, types it groups, folded). The order is the order in the notes.
SECTIONS: Tuple[Tuple[str, Tuple[str, ...], bool], ...] = (
    ("New", ("feat",), False),
    ("Fixes", ("fix",), False),
    ("Performance", ("perf",), False),
    (OTHER, (NO_TYPE,), False),
    ("Internal", INTERNAL_TYPES, True),
)

BREAKING_TITLE = "Breaking changes"

# The commit semantic-release writes when versioning is not a change to the
# project: it would show up as "chore(release): v0.2.0" in the middle of the
# notes.
RELEASE_COMMIT = ("chore", "release")

COMMIT_PATTERN = re.compile(
    r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^)]*)\))?(?P<breaking>!)?:\s*(?P<text>.+)$"
)

VERSION_PATTERN = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')

PRERELEASE_WARNING = (
    "> **Test build.** Published automatically from `develop` so changes can be tried "
    "before they become a definitive version. It may have rough edges; for the latest "
    "stable version go to "
    "[releases](https://github.com/IgnacioBarraza/kobun/releases/latest)."
)

INSTALL = """## Install

### Windows

`kobun.exe` is portable: download it and open it, there is nothing to install.

### Linux

**Recommended**: the `.deb`, which installs the app into the application menu
with its icon.

```
sudo apt install ./kobun_*_amd64.deb
```

The standalone `kobun` binary works on other distributions, but two things to
know: you have to make it executable with `chmod +x` (the download ZIP does not
preserve it) and **modern file managers will not launch a binary on double
click**, so run it from a terminal."""


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Commit:
    hash: str
    type: str
    scope: Optional[str]
    text: str
    breaking: bool


# =========================
# Reading the history
# =========================


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(ROOT), *arguments),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {' '.join(arguments)} failed")

    return result.stdout.strip()


def tag_of_head() -> str:
    """The tag pointing exactly at HEAD, so it does not have to be typed."""
    try:
        return _git("describe", "--tags", "--exact-match", "HEAD")
    except GitError:
        raise SystemExit(
            "HEAD is not tagged: pass the tag as an argument.\n"
            "    python3 scripts/release_notes.py v0.2.0"
        )


def is_prerelease(tag: str) -> bool:
    """`v0.2.0-alpha.1` yes, `v0.2.0` no: the hyphen only appears in the suffix."""
    return "-" in tag.lstrip("vV")


def previous_tag(tag: str, stable_only: bool = False) -> Optional[str]:
    """
    The previous tag reachable from `tag`, or None on a first release.

    It looks from the tag's parent and not from the tag itself, because describe
    would return the tag.

    `stable_only` is what keeps a definitive version from coming out empty: its
    changes were already published in the prereleases, so if the previous tag
    were the last alpha there would be nothing left to tell. Comparing against
    the last stable tag makes the notes cover everything since then.
    """
    arguments = ["describe", "--tags", "--abbrev=0"]
    if stable_only:
        arguments.append("--exclude=*-*")

    try:
        return _git(*arguments, f"{tag}^")
    except GitError:
        return None


def check_revision(revision: str) -> None:
    """
    A tag that does not exist is the easiest mistake to make — writing the tag
    before creating it — and without this it shows up as a git traceback.
    """
    try:
        _git("rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}")
    except GitError:
        raise SystemExit(
            f"{revision} does not exist in this repository.\n"
            "If it is a new tag, create it first:  git tag v0.2.0"
        )


def read_commits(tag: str, since: Optional[str]) -> List[Commit]:
    span = f"{since}..{tag}" if since else tag

    # No merges: "Merge pull request #1 from ..." is not a change, it is how the
    # change got in.
    output = _git("log", span, "--no-merges", f"--pretty=%h{FIELD_SEPARATOR}%s")

    commits = [parse(*line.split(FIELD_SEPARATOR, 1)) for line in output.splitlines() if line.strip()]

    return [commit for commit in commits if not is_release_commit(commit)]


def repository_slug() -> Optional[str]:
    """`user/repo`, to build the comparison link."""
    from_environment = os.environ.get("GITHUB_REPOSITORY")
    if from_environment:
        return from_environment

    try:
        url = _git("remote", "get-url", "origin")
    except GitError:
        return None

    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)

    return match.group(1) if match else None


# =========================
# Classification
# =========================


def parse(short_hash: str, subject: str) -> Commit:
    match = COMMIT_PATTERN.match(subject.strip())

    if match is None:
        return Commit(hash=short_hash, type=NO_TYPE, scope=None, text=subject.strip(), breaking=False)

    scope = match.group("scope")

    return Commit(
        hash=short_hash,
        type=match.group("type").lower(),
        scope=scope.strip() if scope else None,
        text=match.group("text").strip(),
        breaking=match.group("breaking") is not None,
    )


def is_release_commit(commit: Commit) -> bool:
    """The versioning commit is not a change: the release itself writes it."""
    return (commit.type, commit.scope) == RELEASE_COMMIT


def _title_for(commit: Commit) -> str:
    if commit.breaking:
        return BREAKING_TITLE

    for title, types, _ in SECTIONS:
        if commit.type in types:
            return title

    # A type we do not know is still a change: it lands in "Other changes"
    # rather than disappearing from the notes.
    return OTHER


def group(commits: Sequence[Commit]) -> Dict[str, List[Commit]]:
    """
    Groups by section, without repeating texts.

    Duplicates appear on their own with rebases and cherry-picks; in the notes
    they read as if the change had been made twice.
    """
    groups: Dict[str, List[Commit]] = {}
    seen = set()

    for commit in commits:
        key = (commit.type, commit.scope, commit.text)
        if key in seen:
            continue

        seen.add(key)
        groups.setdefault(_title_for(commit), []).append(commit)

    return groups


# =========================
# Writing
# =========================


def _line(commit: Commit) -> str:
    # The text goes exactly as it was committed: capitalising it would break
    # names like `pyproject.toml` or `open_in_default_app`.
    text = f"**{commit.scope}**: {commit.text}" if commit.scope else commit.text

    # GitHub turns the hash into a link to the commit on its own.
    return f"- {text} ({commit.hash})"


def _block(title: str, commits: Sequence[Commit], folded: bool) -> str:
    lines = "\n".join(_line(commit) for commit in commits)

    if folded:
        return f"<details>\n<summary>{title} ({len(commits)})</summary>\n\n{lines}\n\n</details>"

    return f"### {title}\n\n{lines}"


def _section_order() -> List[Tuple[str, bool]]:
    # What breaks compatibility goes first: it is what may force someone to do
    # something before updating.
    return [(BREAKING_TITLE, False)] + [(title, folded) for title, _, folded in SECTIONS]


def build_notes(
    commits: Sequence[Commit],
    tag: str,
    previous: Optional[str],
    slug: Optional[str] = None,
) -> str:
    # Installing goes on top: most people opening a release came to download the
    # app, not to read the changelog. The warning goes before that, when it
    # applies: whoever downloads an alpha has to know before fetching a binary.
    parts = [PRERELEASE_WARNING] if is_prerelease(tag) else []
    parts += [INSTALL, "## Changes"]

    if not commits:
        parts.append(f"No changes recorded{f' since {previous}' if previous else ''}.")
    else:
        if previous is None:
            parts.append("First published version.")

        groups = group(commits)

        for title, folded in _section_order():
            if title in groups:
                parts.append(_block(title, groups[title], folded))

    link = _comparison_link(tag, previous, slug)
    if link:
        parts.append(link)

    return "\n\n".join(parts) + "\n"


def _comparison_link(tag: str, previous: Optional[str], slug: Optional[str]) -> Optional[str]:
    if not slug:
        return None

    base = f"https://github.com/{slug}"

    if previous:
        return f"**Full changelog**: {base}/compare/{previous}...{tag}"

    return f"**Full changelog**: {base}/commits/{tag}"


# =========================
# Version consistency
# =========================


def package_version() -> str:
    """
    The file is read instead of importing the package: that keeps this script
    pure stdlib and independent of kobun being importable on the runner.
    """
    text = (ROOT / "kobun" / "__init__.py").read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(text)

    if match is None:
        raise SystemExit("Could not read __version__ from kobun/__init__.py")

    return match.group(1)


def version_of_tag(tag: str) -> str:
    """`v0.2.0-alpha.1` -> `0.2.0-alpha.1`: only the format's `v` falls off."""
    return tag.lstrip("vV")


def check_version(tag: str) -> None:
    """
    The prerelease suffix is compared too: semantic-release writes
    `0.2.0-alpha.1` into the package, so the app says exactly what the tag says
    and any difference is a real desynchronisation.
    """
    expected = package_version()
    found = version_of_tag(tag)

    if found != expected:
        raise SystemExit(
            f"Tag {tag} does not match the package version ({expected}).\n"
            "The version is shown inside the app, so publishing with this tag\n"
            f"would make Kobun say v{expected} while being release {tag}.\n"
            "Usually this means the tag was created by hand: tags are created by\n"
            "semantic-release when it versions, and there both come from one place."
        )


# =========================
# Entry point
# =========================


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", nargs="?", help="Release tag (defaults to the one pointing at HEAD)")
    parser.add_argument("--from", dest="since", help="Reference tag or commit (defaults to the previous tag)")
    parser.add_argument("--output", type=Path, help="File to write to (defaults to standard output)")
    parser.add_argument(
        "--skip-version-check",
        action="store_true",
        help="Do not require the tag to match kobun.__version__",
    )
    args = parser.parse_args(argv)

    tag = args.tag or tag_of_head()

    if not args.skip_version_check:
        check_version(tag)

    check_revision(tag)

    # A definitive version is compared against the last definitive one; a
    # prerelease, against the tag immediately before it.
    previous = args.since or previous_tag(tag, stable_only=not is_prerelease(tag))
    if previous:
        check_revision(previous)

    try:
        commits = read_commits(tag, previous)
    except GitError as error:
        raise SystemExit(f"git failed: {error}")

    notes = build_notes(commits, tag, previous, repository_slug())

    if args.output:
        args.output.write_text(notes, encoding="utf-8")
        print(f"{args.output}: {len(commits)} commits since {previous or 'the beginning'}", file=sys.stderr)
    else:
        sys.stdout.write(notes)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
