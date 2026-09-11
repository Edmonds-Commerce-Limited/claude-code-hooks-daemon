# Callout: an archival that forgets the age-out is now blocked at commit

**Plan**: 00379
**Audience**: operators

Your main plan index keeps only the 30 highest-numbered completed rows; older
ones move verbatim into `Completed/README.md`. That keeps the entry point to
the plan tree readable without losing a row, and the Plan Completion Checklist
asks for the age-out in the SAME commit as the archival that displaced it.

Until now nothing enforced it at commit time. `terminal-state-atomic` already
made archiving atomic, but it never looked at the row count — so an archival
could add a row and forget to age one out, and every `plan-qa --sweep` would
still report a clean tree. In this repository that happened on three
consecutive archival commits before anything objected.

A new plan QA check, `index-retention-window`, now runs at the commit gate and
in the sweep. It reports how many completed rows the index carries, the window,
and how many rows are overdue for the archive index.

**It does not run at edit time, and that is deliberate.** An archival is
legitimately over the window in between adding the new row and removing the
aged-out ones. Blocking the first of those two writes would deny the first half
of a correct archival and force an artificial ordering on it. Whether the
age-out happened is a property of the finished COMMIT, so that is where it is
judged — the same reasoning that keeps `terminal-state-atomic` commit-only.

**If your index is already over the window**, the first commit after upgrading
will report it. The fix is the one the message names: move the overflow rows
verbatim into `Completed/README.md`, rebasing each link off the `Completed/`
prefix, so the row content a reader sees is unchanged and only its location
moved.

The window is not configurable. The batch guard in
`tests/integration/test_plan_index_navigability.py` and this check now read the
same constant, because two definitions of one ceiling is how they drift apart.
