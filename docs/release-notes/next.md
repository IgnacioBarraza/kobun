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
