# N46 landing merge report

**Plan**: 00466
**Task**: merge `main` into `worktree-n466-n46-clean` and verify (ledger N46 —
the budget-exhaustion advisory scoped to its channel, plus a new
PostToolUseFailure agent-terminated-early detector).

## Merge

`git merge --no-ff main` against pre-merge HEAD `e293a9a01` (gate green).
One real conflict (`CLAUDE/Plan/00466-niggles-ledger-sixteen/PLAN.md`);
everything else auto-merged cleanly.

### Conflict resolution

- **PLAN.md ledger table**: resolved with
  `merge_ledger_table.py`. Output: `rows=98 differs_from_main=['N46'] only_on_branch=[]` — only this branch's own N46 row differed from main's
  copy (expected: this branch owns that ledger entry), and nothing was lost
  or duplicated. Made the trivial N1 row edit (`| N1 |` → `| N1  |`); the
  `markdown_table_formatter` handler auto-realigned every pipe in the table
  on save.
- **CLAUDE.md / .claude/HOOKS-DAEMON.md**: took main's version
  (`git show main:<path> > <path>`, since `git checkout -- <file>` is
  blocked as destructive), then ran `bin/hooks-daemon regenerate-docs`
  — **not** `restart`, which deliberately leaves CLAUDE.md alone in a
  linked worktree (`ClaudeMdInjector`'s `write_in_linked_worktree` guard).
  A plain `restart` left both files byte-identical to main's, silently
  dropping this branch's `agent_terminated_early_failure_detector` guidance
  bullet — caught by
  `tests/integration/test_claude_md_guidance_coverage.py::TestGuidanceActuallyReachesClaudeMd::test_every_earning_handler_has_a_section_in_claude_md`,
  which failed on the first test run for exactly this reason. Re-ran
  `regenerate-docs`, confirmed the handler's bullet was back, then
  `restart`ed the daemon (which leaves the file alone on a subsequent
  restart, as expected) and re-ran the full test list: green.
- **Config-changes manifest, hooks-daemon.yaml(.example), handler
  constants, HANDLER_REFERENCE.md**: auto-merged with both sides' entries
  present; no conflict markers, nothing to reconcile by hand.
- **Release note collision**: this branch's
  `33-budget-exhaustion-advisory-is-now-channel-scoped.md` collided with
  main's own `33-a-fresh-install-no-longer-sets-plansdirectory-or-any-plugin-key.md`.
  Checked the holding-area test
  (`tests/integration/test_pending_release_notes_holding_area.py`): its
  `_CALLOUT_NAME` regex is still `^\d{2}-...` (two digits), and main's
  highest-numbered note is `98-...`, so per the brief `git mv`'d this
  branch's note to `99-budget-exhaustion-advisory-is-now-channel-scoped.md`.
  Its body already carried a valid `**Plan**: 00466` and
  `**Audience**: operators` line; no other edit needed.

No row was lost or duplicated in the ledger table; no `UU` (unresolved)
paths remained in `git status` once the above was staged.

## Tests (worktree venv)

Command list from the brief, run together:
`tests/unit/handlers tests/unit/core tests/unit/utils tests/daemon tests/integration/test_claude_md_guidance_coverage.py tests/integration/test_pending_release_notes_holding_area.py tests/unit/utils/test_reserved_word_command_heads.py`

- First run (before `regenerate-docs`): **1 failed, 14706 passed** — the
  `test_every_earning_handler_has_a_section_in_claude_md` failure above.
- Second run (after `regenerate-docs` + `restart`): **14707 passed**, 6
  warnings (pre-existing `PytestCollectionWarning`s on `TestType`/
  `TestServerHandler` names, unrelated to this merge).

**Known exception, per the brief — reported, not fixed**:
`tests/unit/handlers/test_safety_handlers_hostile_input_performance.py` ran
GREEN here (31 passed) as part of the `tests/unit/handlers` sweep above.
The brief flagged it as red-on-main from a separate issue (N106); on this
merged branch it passed cleanly, so nothing needed fixing regardless.

## QA on changed files (`git diff e293a9a01 --name-only -- '*.py'`, 134

existing files after filtering 3 deletions in `tests/unit/supervise/`)

- **ruff check**: `All checks passed!`
- **black --check**: `134 files would be left unchanged.`
- **mypy**: the real QA gate's scope (`src/ scripts/ install.py examples/ .claude/ccy/claude-supervise.py`, per `scripts/qa/gate-scope.bash`'s
  `qa_type_paths`) does **not** include `tests/`. Filtering the changed-file
  list to that scope and also running the full canonical scope directly
  both gave `Success: no issues found in 677 source files`. (An initial run
  that included changed `tests/*.py` files produced 27 errors — all inside
  `tests/`, none of them in the real gate's scope, and an artifact of
  mypy's explicit-file-list mode losing package/override context that a
  directory-scoped run has; not a real defect.)
- **pyright**: `scripts/qa/run_pyright_check.py` → `pyright 1.1.413: 0 errors, 0 warnings in 1946 files`.

## Daemon

Restarted after resolving the merge (`bin/hooks-daemon restart`);
`bin/hooks-daemon status` confirms `Daemon: RUNNING`.

## Final state

- HEAD: `925978250c3a071984abe36ac73854a2497104d6` (merge commit, on
  `worktree-n466-n46-clean`)
- Gate: **not queued**, per instruction. Nothing pushed.
