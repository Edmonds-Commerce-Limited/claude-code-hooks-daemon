# Callout: the post-upgrade truth-changes report surfaces each truth once

**Plan**: 00362
**Audience**: client projects

`check-truth-changes`, and the doc-reconciliation step of the upgrade skill
that consumes it, no longer replay a truth once per release it changed in.
Entries that share an `id` across releases are one truth revised repeatedly,
and the report now shows only the current form, marked `(v3.26.0, revised in v3.23.0, v3.25.0)` — so an agent following the report is never told to write a
claim into your docs and then contradict it twice, as it was for the
plan-creation truth. Manifest authors give a revising entry the same `id` as
the entry it supersedes; un-keyed entries are untouched.
