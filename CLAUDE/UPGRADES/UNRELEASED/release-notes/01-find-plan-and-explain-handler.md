# Callout: finding a plan, and explaining a project handler

**Plan**: 00413
**Audience**: everyone

`hooks-daemon find-plan <number|name|words>` searches the whole plan tree,
archives included, and prints each match's number, status and path. It exists
because the guard that blocks hand-creating a plan folder was denying the only
obvious way to look one up, without naming an alternative — a folder scan also
misses everything under `Completed/`, which `find-plan` does not.

`hooks-daemon explain-handler <name>` now resolves **project** handlers as well
as library ones. The generated `CLAUDE.md` lists a project's own handlers and
tells the reader to look them up with exactly that command, and until now the
first entry in that list answered "unknown handler" — the handler that had just
fired on your previous command read as nonexistent. Rule lookups are unchanged:
project handlers declare no rules, so `explain-rule --list` omitting them was
always correct.
