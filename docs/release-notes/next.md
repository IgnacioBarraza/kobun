<!--
What someone reading the next release's page sees first.

Write it as you work, not on release day: two lines per change, as soon as it is
done. It is the only part of the pipeline that is not generated, because the
context —what you can do now that you could not before— is not in the commits.

In English, like the rest of the release page.

Rules:

- Say what changes for whoever uses the app, not which file you touched.
  Yes:  "The page field now says how many pages the selection covers."
  No:   "Implement selection feedback in PdfViewModel."
- Group by change, not by commit. Six commits about one screen are one entry.
- A fix is worth saying what used to break.
- Comments like this one are never published: the generator strips them.

Alphas show this file as it stands, marked as in progress. The definitive
version shows it as the final summary. Both read the same file, because an alpha
and the version it leads to are the same work.

Filed automatically when a definitive version is released — semantic-release
runs `--archive-released` before it commits. To do it by hand:

    python3 scripts/release_notes.py --archive v0.4.0
-->

### Page preview while splitting

The splitting screen now shows the page you are about to export, beside the
options. It follows the first page of your selection, tells you whether the page
on screen is one of the pages that will be exported, and steps through the
document with the arrows.

**Ver más grande** opens it at reading size in a window shaped to the page: tall
for a portrait page, wide for a landscape one.

### Live page count

The page field says how many pages the selection covers while you type it, and
explains why a range cannot be used instead of only disabling the button:
`1-5,20` on a twelve page PDF now tells you page 20 does not exist.

It also speaks up when the selection is not what it looks like: `3-8,1-5` is
eight pages and not thirteen, because overlapping ranges are merged.

### Fixes

- A selection the document cannot satisfy no longer leaves the button enabled to
  fail with a dialog after the click.
- Choosing an output folder by hand and then opening another PDF moved the files
  next to the new PDF, silently, with the chosen name still on screen.
