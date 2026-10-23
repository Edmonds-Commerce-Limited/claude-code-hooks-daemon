# Callout: a plan journal is one file per entry, and existing journal files are closed

**Plan**: 00543
**Audience**: operators

`mkplan.bash --journal <plan> <category> <body-file>` now writes each entry as its own file, `JOURNAL/YYYY-MM-DD/HHMMSSZ-<category>-<hex>.md`, instead of appending to a per-day file. Two sessions journalling the same plan on the same day no longer touch the same file, so merge conflicts in journals are gone. Existing `NNNNN-Journal-YY-MM-DD.md` day-files stay valid and are read as before, but are read-only.

Hand edits of any journal file are denied: `plan_journal_guard` refuses to create an entry file by hand or change an existing one (only removing conflict markers, or restoring the committed bytes, passes). The `journal-dayfile-is-today` check now closes existing journal files at edit time and has a commit half that blocks a staged modification or deletion of an entry file, or a rename that changed its content; a pure rename (archiving a plan) is clean. The other journal checks, the plan templates and the docs read entry files and legacy day-files alike. Reported as issue #135.
