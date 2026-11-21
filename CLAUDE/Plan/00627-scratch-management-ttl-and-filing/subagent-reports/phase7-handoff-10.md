# Phase 7 handoff 10 (7.1 and 7.4 done; both reported failures resolved)

## Done

- a6067e409: the `test_documented_commands_are_not_self_denied` failure was NOT pre-existing. Commit 6648e4580 added the
  `HANDLER_REFERENCE.md` example, and it is not on origin/main. Its `<session>` placeholder parsed as a redirect out of
  the repository. Fixed with a concrete name.
- The child-pytest INTERNALERROR in `test_project_containment.py` is an invocation artefact, not a code defect. It is
  reproduced by running the worktree's tests with the MAIN checkout's venv plus `PYTHONPATH=src`. The parent passes
  because PYTHONPATH masks the venv, but `run_child_pytest` drops PYTHONPATH. The child then imports `/workspace/src`,
  and `tests/source_tree_guard.py` raises `SourceTreeMismatch` at `pytest_sessionstart`. With the worktree's own venv:
  1 passed and 332 passed, and a 24k-test pre_tool_use+utils run had no INTERNALERROR. No fix needed: the guard is
  doing its job.
- That broad run found one real failure, now fixed in 9668f01f4: `ScratchCapGuardHandler` and
  `ScratchUnownedEntryHandler` were unclassified in `test_blocking_handler_evasion.py`.
- 0fdad9b2e and 9668f01f4 finish Task 7.1. `DEFAULT_HANDOFF_GLOBS` still includes `untracked/scratch/**`, because
  DESIGN X5 resolves this by guidance and the no-plan fallback plus `commit -F` files still need that glob.
- d364646dd finishes Task 7.4: the refresher reference section, release note 021 and the caps config-change wording.

## For the coordinator

- Plan 00560 has no branch and its PLAN.md is untouched. 00627 carried its Task 2.1 wording and the `src/` part of its
  Task 2.3; tell its owner.
- The deployed `.claude/skills/` copies were refreshed from source for the 7 edited skill files.

## Remaining in this plan

Task 6.3 (blocked on 00623) and Phase 8.
