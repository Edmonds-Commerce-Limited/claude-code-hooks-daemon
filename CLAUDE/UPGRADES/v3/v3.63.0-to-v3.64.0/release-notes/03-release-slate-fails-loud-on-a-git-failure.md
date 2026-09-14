# Callout: a failing git listing no longer reads as a clean slate

**Plan**: 00364
**Audience**: operators

`release-slate-check` decides the slate is clean partly from "no branches
ahead, no live worktrees". Both came from a helper that returned an empty
list when git itself failed, so a broken `git worktree list` or
`git for-each-ref` CONTRIBUTED to a clean verdict — the opposite of the rule
the same module already applied to a CI lookup. A failed read is now carried
into the report, printed as `Slate: UNDETERMINED` with the command that
failed, and exits `1` rather than `0`. As with any other could-not-determine,
`--accept` does not rescue it: acknowledging work in flight is not
acknowledging blindness. The JSON output gained an `undetermined_reason`
field alongside `clean`.
