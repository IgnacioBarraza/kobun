# Releasing

Nothing is tagged by hand. The version comes from the commits, through
[python-semantic-release](https://python-semantic-release.readthedocs.io/),
configured under `[tool.semantic_release]` in
[`pyproject.toml`](../pyproject.toml). Push to a release branch and the pipeline
decides whether there is a version to publish, and which one.

## What the commits decide

| Commit prefix | Effect on the version |
|---|---|
| `feat:` | minor — `0.1.0` → `0.2.0` |
| `fix:` `perf:` | patch — `0.1.0` → `0.1.1` |
| `feat!:` or `BREAKING CHANGE:` | minor while below 1.0.0 (`major_on_zero = false`) |
| `docs:` `chore:` `ci:` `refactor:` `test:` `style:` `build:` | nothing — no release |
| anything without a `type:` prefix | nothing, and it never reaches the changelog |

That last row is the one that bites. `Fix drag and drop crash` is not a
conventional commit — no colon, no type — so it publishes nothing, and the
pipeline stays green while the fix never reaches anyone. Write `fix: drag and
drop crash` instead.

Two branches release:

| Branch | Version | GitHub release |
|---|---|---|
| `develop` | `0.2.0-alpha.1`, `.2`, … | marked **pre-release** |
| `main` | `0.2.0` | the definitive one |

So a merge into `develop` gives you installable binaries to try before the
version is final, and the merge from `develop` into `main` turns the accumulated
alphas into the stable release.

## What the pipeline does

When there is something to publish, it bumps the version in
[`kobun/__init__.py`](../kobun/__init__.py) and in
[`packaging/kobun.iss`](../packaging/kobun.iss), inserts the entry into
[`changelog.md`](changelog.md), commits that as
`chore(release): vX.Y.Z [skip ci]`, tags it, creates the release, and only then
builds the binaries from the tag and attaches them. Nothing to publish means
nothing happens — no empty release, no tag.

**Preview what a release would say**, before pushing anything:

```bash
pip install -e .[release]
semantic-release version --print          # the next version, or the current one if none
python3 scripts/release_notes.py v0.2.0   # the release body, once the tag exists
```

## Going to 1.0.0

While the project is below `1.0.0`, `major_on_zero = false` keeps a breaking
change from bumping the major: `feat!:` yields `0.3.0`, not `1.0.0`. That is
deliberate — `1.0.0` is a statement, not a number, and it should be made on
purpose rather than by a commit message.

When the API is ready to be called stable, set `major_on_zero = true` and land
the breaking commit in the same pull request. From then on that setting no
longer applies —it only governs the `0.x` range— and every `feat!:` produces the
next major on its own.

## After a definitive release

A release writes a real commit —the version bump plus the changelog entry— on
the branch it publishes from. After releasing from `main`, that leaves `main` one
commit ahead of `develop`, on three files nobody edits by hand
(`kobun/__init__.py`, `packaging/kobun.iss`, `docs/changelog.md`). Left alone,
the next `develop` → `main` pull request conflicts on all three, and resolving it
the wrong way walks the published version backwards.

The `back-merge` job merges `main` into `develop` right after a definitive
release, so `develop` carries the version it just published and the next pull
request has nothing to conflict on. It runs only for definitive releases —a
prerelease publishes from `develop` itself, so there is nothing to bring back—
and shares the `release` concurrency group so a prerelease cannot interleave
with the merge. If the merge does conflict, the job fails with the command to
resolve it by hand rather than forcing anything.

## The release bot

The release commit lands on a protected branch, and `GITHUB_TOKEN` cannot push
there — a ruleset only exempts named actors. So the versioning job authenticates
as a GitHub App, **kobun-release-bot**, which the ruleset lists as a bypass
actor. [`actions/create-github-app-token`](https://github.com/actions/create-github-app-token)
exchanges the app's private key for an installation token that lives for an hour.

What the repository has to provide, both scoped to the **`KOBUN_RELEASE`**
environment — which is why the versioning job declares `environment:
KOBUN_RELEASE`. A job that does not declare it sees them as empty, and the token
step fails with `appId option is required`:

| Where | Name | What it is |
|---|---|---|
| Environment variable | `APP_ID` | the App's numeric ID |
| Environment secret | `APP_PRIVATE_KEY` | the `.pem` private key, whole file including the BEGIN/END lines |

The App needs **Contents: Read and write** (pushing, tagging and creating
releases all live under that permission), has to be installed on this
repository, and has to appear in the bypass list of the branch ruleset.

One consequence worth knowing: a push made with `GITHUB_TOKEN` never triggers
workflows, but **a push made with an App token does**. The release commit would
therefore start another run of this same workflow. Two things prevent the loop —
the `[skip ci]` that `commit_message` puts in the commit, and the
`github.actor != 'kobun-release-bot[bot]'` guard on the job.

Uploading the binaries does not need the App: attaching an asset to a release
touches no branch, so the ruleset never sees it and `GITHUB_TOKEN` is enough.

## Two documents, on purpose

[`changelog.md`](changelog.md) is the **record**: every version, in
semantic-release's own format, written by the tool.

The GitHub release body is the **shop window**, written by
[`scripts/release_notes.py`](../scripts/release_notes.py): it leads with the
install instructions, groups changes under plain headings (*New*, *Fixes*,
*Performance*), folds `refactor:`/`chore:`/`ci:` away in a `<details>`, and warns
when the download is a pre-release.

It also fixes something the record cannot: semantic-release attributes each
commit to the tag that first published it, so a stable release that follows a
string of alphas has **nothing left of its own** and its notes come out empty.
The generator compares a definitive version against the last definitive
version — not against the last alpha — so the release that people actually
download lists everything that changed since the previous one they had.

Commits that do not follow the convention are never dropped from the notes: they
land in *Other changes*. They just do not move the version.
