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

A release page has two layers. The **summary** comes from
docs/release-notes/next.md and is written by hand, because what a version gives
someone is not in the commits: "implement page preview functionality with
caching" and five variations of it say nothing to whoever downloads the app.
The **commit log** is generated as before and folded underneath, so nothing is
hidden and nothing shouts.

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

OTHER = "Other Changes"

# (title, the types it groups). The order is the order on the page.
#
# The names are the ones conventional-changelog uses, so a Kobun release reads
# like every other release someone has seen. Maintenance gathers what does not
# change the app itself; it is listed rather than hidden, because "there were no
# changes" and "the changes were internal" are different things.
SECTIONS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Features", ("feat",)),
    ("Bug Fixes", ("fix",)),
    ("Performance Improvements", ("perf",)),
    ("Documentation", ("docs", "doc")),
    ("Tests", ("test", "tests")),
    ("Maintenance", ("refactor", "chore", "build", "ci", "style", "revert")),
    (OTHER, (NO_TYPE,)),
)

BREAKING_TITLE = "Breaking Changes"

# The commit semantic-release writes when versioning is not a change to the
# project: it would show up as "chore(release): v0.2.0" in the middle of the
# notes.
RELEASE_COMMIT = ("chore", "release")

COMMIT_PATTERN = re.compile(
    r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^)]*)\))?(?P<breaking>!)?:\s*(?P<text>.+)$"
)

VERSION_PATTERN = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')

HIGHLIGHTS_DIRECTORY = ROOT / "docs" / "release-notes"
HIGHLIGHTS_FILE = HIGHLIGHTS_DIRECTORY / "next.md"

# Everything between these is guidance for whoever writes the file, not for
# whoever reads the release.
COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)

# The `# v0.4.0` an archived summary opens with.
TITLE_PATTERN = re.compile(r"\A#\s+\S+[^\n]*\n")

STABLE_SUMMARY_TITLE = "## What's new in {version}"
PRERELEASE_SUMMARY_TITLE = "## What is being tried, on the way to {version}"

MISSING_SUMMARY_WARNING = (
    "No summary was written for this version. "
    "The changes are listed below, in the words of their commits."
)

CHANGES_SUMMARY = "All changes ({count})"

PRERELEASE_WARNING = (
    "> **Test build on the way to {version}.** Published automatically from `develop` "
    "so changes can be tried before they become a definitive version. It may have "
    "rough edges; for the latest stable version go to "
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

    for title, types in SECTIONS:
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


def _capitalized(text: str) -> str:
    """
    The description as a sentence, unless its first word is an identifier.

    Capitalising blindly would turn `pyproject.toml` into `Pyproject.toml` and
    `open_in_default_app` into something that no longer names anything, so a
    first word carrying a dot, an underscore or a backtick is left alone.
    """
    first = text.split(" ", 1)[0]

    if not first or not first[0].islower() or set("._`(/") & set(first):
        return text

    return text[0].upper() + text[1:]


def _line(commit: Commit, slug: Optional[str] = None) -> str:
    description = _capitalized(commit.text)
    body = f"**{commit.scope}:** {description}" if commit.scope else description

    # An explicit link rather than a bare hash: GitHub turns one into the other
    # on a release page, but these notes are also written to the job summary and
    # read from the terminal, where a bare hash is just seven characters.
    reference = (
        f"([{commit.hash}](https://github.com/{slug}/commit/{commit.hash}))"
        if slug
        else f"({commit.hash})"
    )

    return f"* {body} {reference}"


def _block(title: str, commits: Sequence[Commit], slug: Optional[str] = None) -> str:
    lines = "\n".join(_line(commit, slug) for commit in commits)

    return f"### {title}\n\n{lines}"


def _section_order() -> List[str]:
    # What breaks compatibility goes first: it is what may force someone to do
    # something before updating.
    return [BREAKING_TITLE] + [title for title, _ in SECTIONS]


def build_notes(
    commits: Sequence[Commit],
    tag: str,
    previous: Optional[str],
    slug: Optional[str] = None,
    highlights: Optional[str] = None,
) -> str:
    """
    The release page, in the order someone reads it.

    The summary goes first: it is two or three lines and it is the only part
    that answers "what does this version give me". Install follows, because most
    people opening a release came to download the app. The commit log goes last,
    folded when there is a summary to fold it under — six commits saying
    "implement page preview" are the record of the work, not a description of
    it, and they should not be the first thing on the page.
    """
    parts: List[str] = []

    if is_prerelease(tag):
        parts.append(PRERELEASE_WARNING.format(version=base_version(tag)))

    summary = summary_block(tag, highlights)
    if summary:
        parts.append(summary)

    parts.append(INSTALL)
    parts.extend(
        _change_blocks(commits, tag, previous, folded=highlights is not None, slug=slug)
    )

    return "\n\n".join(parts) + "\n"


def _change_blocks(
    commits: Sequence[Commit],
    tag: str,
    previous: Optional[str],
    folded: bool,
    slug: Optional[str] = None,
) -> List[str]:
    """
    The commit log, either as the page's main content or as a detail underneath.

    Breaking changes never fold: they are the one thing that can make an update
    cost someone work, and they have to be visible without a click.
    """
    heading = _changes_heading(tag, previous, slug)

    if not commits:
        since = f" since {previous}" if previous else ""
        return [f"{heading}\n\nNo changes recorded{since}."]

    groups = group(commits)
    blocks: List[str] = []

    if BREAKING_TITLE in groups:
        blocks.append(_block(BREAKING_TITLE, groups[BREAKING_TITLE], slug))

    sections = [
        _block(title, groups[title], slug)
        for title in _section_order()
        if title in groups and title != BREAKING_TITLE
    ]

    if previous is None:
        sections.insert(0, "First published version.")

    if not sections:
        return blocks

    if not folded:
        return blocks + [heading] + sections

    body = "\n\n".join([heading] + sections)
    count = len(commits)

    return blocks + [
        f"<details>\n<summary>{CHANGES_SUMMARY.format(count=count)}</summary>\n\n{body}\n\n</details>"
    ]


def _changes_heading(tag: str, previous: Optional[str], slug: Optional[str]) -> str:
    """
    `## [0.4.0](compare link) (2026-09-13)`, the shape conventional-changelog
    writes and everyone has read before.

    The date comes from the tag itself rather than from today: notes can be
    regenerated months later, and a release should not claim to have happened
    when someone re-ran the script.
    """
    version = version_of_tag(tag)
    date = tag_date(tag)
    title = f"[{version}]({_compare_url(tag, previous, slug)})" if slug else version

    return f"## {title}{f' ({date})' if date else ''}"


def _compare_url(tag: str, previous: Optional[str], slug: str) -> str:
    base = f"https://github.com/{slug}"

    return f"{base}/compare/{previous}...{tag}" if previous else f"{base}/commits/{tag}"


def tag_date(tag: str) -> Optional[str]:
    """The day the tag was made, as YYYY-MM-DD."""
    try:
        return _git("log", "-1", "--format=%ad", "--date=short", tag)
    except GitError:
        return None


# =========================
# The hand-written summary
# =========================


def read_highlights(path: Optional[Path] = None) -> Optional[str]:
    """
    The summary held in one file, or None when it holds none.

    The guidance lives in HTML comments so it can be long and blunt without any
    of it reaching the release page. A file that is nothing but comments counts
    as empty, which is what `next.md` is right after a version ships.

    A leading `# v0.4.0` is dropped: the archived files carry one so they read as
    documents on their own, and the release page already says which version it
    is in its own title.
    """
    source = path or HIGHLIGHTS_FILE

    if not source.exists():
        return None

    stripped = COMMENT_PATTERN.sub("", source.read_text(encoding="utf-8")).strip()
    stripped = TITLE_PATTERN.sub("", stripped, count=1).strip()

    return stripped or None


def highlights_for(tag: str) -> Optional[str]:
    """
    The summary that belongs to `tag`, from the file that belongs to it.

    An archived version reads its own file. The version being prepared reads
    `next.md`, and *only* it: regenerating the notes of an old tag used to pick
    up whatever was being written for the next version, and publish it as if it
    had shipped back then.

    "Being prepared" is decided by the package version, which semantic-release
    bumps to the version it is releasing — so during a release they match, and
    for any older tag they do not.
    """
    for name in (tag, version_of_tag(tag)):
        archived = HIGHLIGHTS_DIRECTORY / f"{name}.md"
        if archived.exists():
            return read_highlights(archived)

    if base_version(tag) == package_version().split("-", 1)[0]:
        return read_highlights(HIGHLIGHTS_FILE)

    return None


def base_version(tag: str) -> str:
    """
    `v0.4.0-alpha.1` -> `0.4.0`: the version an alpha is on its way to.

    A test build is easier to place when it says which version it belongs to
    rather than just calling itself a test build.
    """
    return version_of_tag(tag).split("-", 1)[0]


def summary_block(tag: str, highlights: Optional[str]) -> Optional[str]:
    """
    The summary section, titled for what the tag is.

    A prerelease with nothing written gets no section at all: it is a test build
    and the warning above already says so. A definitive version says out loud
    that nobody wrote one, because a release page with no summary is a mistake
    and hiding it would only make it repeat.
    """
    version = base_version(tag)

    if highlights is None:
        if is_prerelease(tag):
            return None

        return f"{STABLE_SUMMARY_TITLE.format(version=version)}\n\n{MISSING_SUMMARY_WARNING}"

    title = PRERELEASE_SUMMARY_TITLE if is_prerelease(tag) else STABLE_SUMMARY_TITLE

    return f"{title.format(version=version)}\n\n{highlights}"


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


def _readable(path: Path) -> str:
    """
    A path as it would be typed, falling back to the absolute one.

    `relative_to` raises when the path is not under the root, and a message that
    can raise inside `archive_released` would abort a release over a cosmetic
    detail.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def archive_highlights(tag: str, directory: Optional[Path] = None) -> int:
    """
    Files the summary that was just published and leaves an empty one behind.

    Run after a definitive version, so the next one does not open with the
    previous one's text still in it. Kept as a command rather than done by the
    pipeline: it rewrites a file in the repository, and a release that also
    commits is a release that can fail halfway.
    """
    folder = directory or HIGHLIGHTS_DIRECTORY
    source = folder / "next.md"
    highlights = read_highlights(source)

    if highlights is None:
        print(f"Nothing to file: {source} has no summary.", file=sys.stderr)
        return 1

    target = folder / f"{tag}.md"
    target.write_text(f"# {tag}\n\n{highlights}\n", encoding="utf-8")

    template = COMMENT_PATTERN.search(source.read_text(encoding="utf-8"))
    source.write_text(f"{template.group(0)}\n" if template else "", encoding="utf-8")

    print(f"{target}: filed. {source} is empty again.", file=sys.stderr)

    return 0


def _stage(path: Path) -> None:
    """
    Puts a path in the index, so the release commit carries it.

    semantic-release commits whatever is staged, which is the only hook there is
    for adding a file to that commit: its `assets` setting is for files uploaded
    *to the release page*, and pointing it at this folder failed the release with
    "Is a directory" after the release had already been created.

    A failure here is reported and swallowed: the summary is already filed on
    disk, and refusing to publish over an unstaged file would be worse than the
    file being committed by hand afterwards.
    """
    try:
        _git("add", "--", str(path))
    except GitError as error:
        print(f"warning: could not stage {_readable(path)}: {error}", file=sys.stderr)


def archive_released(version: Optional[str] = None) -> int:
    """
    Files the summary of the version being released, if it is a definitive one.

    Called by semantic-release through `build_command`, which runs **before** the
    release commit and hands over NEW_VERSION — so the archived file and the
    emptied `next.md` travel inside the commit that bumps the version, with no
    second commit and nothing to remember.

    It never fails the release. A build command that exits non-zero aborts the
    whole thing, and not having written a summary is a reason to be told off, not
    a reason to stop publishing.
    """
    released = version or os.environ.get("NEW_VERSION", "")

    if not released:
        print(
            "NEW_VERSION is not set: nothing filed. This runs from semantic-release's "
            "build_command, which sets it.",
            file=sys.stderr,
        )
        return 0

    # An alpha is the same work still in progress: its summary has to survive
    # until the definitive version ships.
    if is_prerelease(released):
        print(f"{released} is a prerelease: the summary stays for the definitive version.",
              file=sys.stderr)
        return 0

    tag = f"v{version_of_tag(released)}"

    if read_highlights() is None:
        print(
            f"warning: {_readable(HIGHLIGHTS_FILE)} is empty, so {tag} is being "
            "published with only its commit log.",
            file=sys.stderr,
        )
        return 0

    archive_highlights(tag)
    _stage(HIGHLIGHTS_DIRECTORY)

    return 0


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
    parser.add_argument(
        "--archive",
        metavar="TAG",
        help="File the current summary under docs/release-notes/<TAG>.md and start a new one",
    )
    parser.add_argument(
        "--archive-released",
        action="store_true",
        help="File it for the version in NEW_VERSION, if that version is a definitive one",
    )
    args = parser.parse_args(argv)

    if args.archive_released:
        return archive_released()

    if args.archive:
        return archive_highlights(args.archive)

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

    highlights = highlights_for(tag)

    if highlights is None and not is_prerelease(tag):
        print(
            f"warning: no summary in {_readable(HIGHLIGHTS_FILE)}; "
            f"{tag} will be published with only its commit log.",
            file=sys.stderr,
        )

    notes = build_notes(commits, tag, previous, repository_slug(), highlights)

    if args.output:
        args.output.write_text(notes, encoding="utf-8")
        print(f"{args.output}: {len(commits)} commits since {previous or 'the beginning'}", file=sys.stderr)
    else:
        sys.stdout.write(notes)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
