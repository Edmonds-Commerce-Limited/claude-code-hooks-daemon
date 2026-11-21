# Task 6.2 build: handoff 8

Ruling: `/workspace/untracked/agent-reports/261121-task-6-2-ruling.md`. Previous: `261121-task-6-2-build-handoff-7.md`. Worktree `/workspace/.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`. Commits are on top of `4739172a4` only.

## Done

- `8653f912d`: `tests/unit/daemon/test_worktree_evacuate_blockers.py`, real-repository `worktree-reap --reap` tests for PROTECTED, REFERENCED, STUCK, liveness unknown, foreign owner, no birth stamp and incomplete walk. Each: kept, scratch inodes unchanged, no store, question never asked. Each seen red under a mutation (journal entry `JOURNAL/2026-11-21/151758Z-action-105f10.md` lists them).
- `8a32e1c21`: `scratch-sweep status` prints `from checkout: <path>` for an archive packed outside the main checkout; `--json` carries `checkouts`. Tests: `tests/unit/daemon/test_worktree_evacuate_status.py` (red first).
- Final commit: a blocker-outside-scratch test (red under `only_scratch` any()), PLAN.md Task 6.2 ticked, the journal entry, this handoff.

## Findings

- No production bug found.
- A plain local `git clone` hard-links objects, so a clone in scratch classifies STUCK, not PROTECTED. The test uses `--no-hardlinks`.
- Liveness unknown marks the whole report incomplete, so the gate says "classification incomplete", not a per-row STUCK.

## Not done

- No full gate run (targeted only, as briefed).
