# Callout: a journal correction is now its own category

**Plan**: 00422
**Audience**: client projects

Plan journals have a seventh entry category, `correction`, which corrects an
earlier entry without editing or moving it. Append one with
`mkplan.bash --journal <plan-number> correction <body-file> --ref 09:50`. The
`--ref` names the corrected entry: `HH:MM` in today's day-file, or
`YY-MM-DD/HH:MM` in an earlier one. The script refuses a correction whose
entry does not exist. Previously, correcting a future-dated stamp produced a
`journal-entry-ordering` advisory that nothing could clear, because the
honest correction was earlier than the entry it corrected. An entry that a
correction in the same day-file names now no longer counts for time order,
so that advisory clears. The shipped `_JOURNAL_TEMPLATE_.md`, `mkplan.bash`
and `PlanJournalling.md` are updated, and the append-only and ordering
advisories now point to the `correction` command. Update any agent briefs
that list six journal categories.
