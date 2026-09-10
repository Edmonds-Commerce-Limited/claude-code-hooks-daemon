# Phase 4 verification report — Plan 00367

## Scope

Verify and finish Plan 00367 Phase 4 (the `Worktree.core.md` merge-approval
gate) in `worktree-plan-00367`, picking up from a prior agent's WIP handoff
commit (`41391a66`) plus diagnostics from an even earlier pass that reported
two defects.

## What was found

Both defects named in the handoff were already fixed on disk before this
session made any code change:

- `cmd_approve_merge` was wired into `daemon/cli.py`'s argparse subparsers
  (`approve-merge`), mirroring `cmd_approve_plan_close`.
- `merge_target()` in `handlers/pre_tool_use/merge_to_main_approval.py`
  correctly imports and calls
  `utils.quoted_spans.blank_shell_literal_spans`, and
  `HandlerID`/`Priority`/`RuleID.MERGE_TO_MAIN_APPROVAL` all exist in
  `constants/{handlers,priority,rule_ids}.py`.

Also confirmed already correct: the handler is exported from
`handlers/pre_tool_use/__init__.py`'s `__all__`, and the config DI chain is
wired end to end — `Config.worktree` (`WorktreeConfig`) ->
`cli.py`'s `controller.initialise(worktree=config.worktree, ...)` ->
`handlers/registry.py`'s `register_all(worktree=...)` ->
`_merge_to_main_requires_human_approval` injected onto every GIT-tagged
handler instance.

This session's own contribution was therefore verification, not additional
implementation: `git fetch origin && git merge origin/main` (clean, no
conflicts — brought in the 00291 upgrade-path-hardening merge and the 00368
journal correction; `cli.py`'s auto-merge preserved the `approve-merge`
subcommand), then a full re-derivation of every acceptance criterion in
`PLAN.md`'s Phase 4 tasks and success criteria, all of which were already
ticked by the prior agent.

## Verification performed

| Check                                                                                                 | Result                                                                                                               |
| ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Targeted unit suites (merge-to-main approval, one-shot approval, approve-merge CLI, close-approval)   | 47 passed                                                                                                            |
| Bash-write-blindness coverage + blocking-handler-evasion classification                               | 222 passed                                                                                                           |
| `tests/unit/docs_qa/`                                                                                 | 473 passed                                                                                                           |
| `tests/unit/plan_qa/` + plan-close-approval + plan-qa-edit                                            | 741 passed                                                                                                           |
| Config-changes/release-notes manifest tests                                                           | 22 passed                                                                                                            |
| `bin/hooks-daemon docs-qa --sweep`                                                                    | 0 `unenforced-approval-gate` findings; 4 pre-existing unrelated advisories (confirmed untouched by this plan's diff) |
| Template vs. deployed `Worktree.core.md`                                                              | byte-identical                                                                                                       |
| `AgentTeam.md`                                                                                        | carries the same "toggle, not unenforced gate" rewrite                                                               |
| `bin/hooks-daemon plan-qa --check-staged`                                                             | 0 findings                                                                                                           |
| `bin/hooks-daemon regenerate-docs`                                                                    | no diff (already current)                                                                                            |
| `npx pyright` (`--pythonpath` into the worktree's untracked venv) on every Phase 2-4 source/test file | 0 errors, 0 warnings                                                                                                 |
| Daemon restart                                                                                        | RUNNING, 31/31 per-event listeners active                                                                            |
| `./scripts/qa/llm_qa.py all`                                                                          | 25/26 PASSED                                                                                                         |

## The one QA failure

`tests` category: 21864 passed, 2 failed, 20 skipped, coverage 95.4%.
Failures: `test_daemon_smoke.py::test_daemon_processes_session_start_hook`
and `::test_daemon_handles_invalid_hook_input`. Confirmed **not a
regression**: `git diff <merge-base>..HEAD -- tests/integration/test_daemon_smoke.py`
is empty (this plan's diff never touches that file), and both tests pass
cleanly in isolation (10/10 in the file). Matches a full-suite-only
daemon-lifecycle fixture flake already documented in this plan's own journal
(08:27 entry, from the Phase 2/3 QA pass). Left unfixed as out of scope.

## What was committed

- `c85b6a20` — merge `origin/main` into `worktree-plan-00367`.
- `49e5077f` — journal entry recording the verification pass and QA results.

Both pushed to `origin/worktree-plan-00367`.

## Deliberately not done

`PLAN.md`'s `**Status**` stays `In Progress`, even though every task and
success criterion is checked and Milestone D is delivered.
`terminal-state-atomic` (a Stage 2 BLOCK-level commit-gate check) denies any
commit that flips a PLAN.md to a terminal status unless the **same commit**
also `git mv`s the plan folder into `Completed/` and updates the README
index — exactly the two actions this session was told not to perform
(archiving happens on `main`, not in the worktree). Flipping Status here
would either be blocked outright by that check or leave the plan
terminal-but-unarchived, the exact inconsistent window the check exists to
prevent. `CLAUDE/Plan/README.md` was not touched and the plan folder was not
`git mv`d, per instruction.

## Unresolved items for the coordinator

1. The atomic terminal-status-flip + archive-into-`Completed/` +
   README-index commit for Plan 00367, on `main`, after this branch merges.
2. `tests/integration/test_plan_index_navigability.py::test_completed_rows_stay_within_the_retention_window`
   (31 completed rows against a window of 30) — pre-existing, unrelated to
   Phase 4, already logged in the 09:25 journal entry with the exact fix
   (age out 00330 and 00336 in the same commit that adds 00367's row).
