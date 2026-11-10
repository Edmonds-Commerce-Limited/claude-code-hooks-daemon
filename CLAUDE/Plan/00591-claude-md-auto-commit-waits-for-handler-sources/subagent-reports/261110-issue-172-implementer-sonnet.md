# Plan 00591 Task 1.1 report (GitHub #172)

RED: with the five new tests in `TestAutoCommitWaitsForHandlerSources` and no implementation,
3 failed on behaviour (`AssertionError: CLAUDE.md must stay dirty` for the untracked plugin source,
`assert '' != ''` for the modified project source, outside-repo debug log missing) and the library
test failed with `AttributeError: ... no attribute '_external_handler_sources'`; the clean case
passed (it asserts unchanged behaviour).

GREEN: `ClaudeMdInjector._external_handler_sources` derives source files from the already-loaded
handler classes (no controller change, no re-loading): any class not defined under the daemon package
dir counts as plugin/project. `_uncommitted_handler_source` makes ONE lock-free
`run_git status --porcelain -- <paths>` call (plus `rev-parse --show-toplevel`); sources outside the
repo are skipped with a debug log; a git failure holds the commit. `_auto_commit_if_dirty` takes an
optional `handler_sources` (default empty, so existing callers are unchanged) and logs one info line
naming the file when it holds back.

Departure from the brief: `inspect.getsourcefile` needs `sys.modules`, which a file-loaded plugin may
lack, so it falls back to the `co_filename` of a method the class defines.

Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/025-...md`.
