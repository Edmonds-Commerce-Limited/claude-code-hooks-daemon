# Callout: a merge conflict in a plan journal day-file now has a sanctioned resolution

**Plan**: 00474
**Audience**: everyone

When two branches each add an entry to the same plan `JOURNAL/` day-file, the merge conflicts, and until now every route out was wrong: `plan_qa_edit` refuses an `Edit` of a day-file dated before today, `plan_journal_guard` refuses a copied-in file, and `git checkout --ours` silently drops the other side's entries. `CLAUDE/Plan/mkplan.bash --resolve-conflict <day-file>` now writes the union of both sides and stages it: the header once, every entry exactly once, in time order, each keeping its original time and day, with ours first on equal `HH:MM` stamps. It refuses, and writes nothing, when the path is not a day-file, holds no conflict, has only one side, or has text it cannot read as a header followed by `## HH:MM` entries. `git checkout|restore --ours|--theirs` of a day-file is still allowed but now draws an advisory naming the new mode, because it discards the other side's entries. The scaffolder is refreshed on upgrade; see `CLAUDE/PlanJournalling.md`.
