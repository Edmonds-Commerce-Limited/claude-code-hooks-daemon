# Task 6.2 build: handoff 7

Ruling: `/workspace/untracked/agent-reports/261121-task-6-2-ruling.md`. Previous: `261121-task-6-2-build-handoff-6.md`. Worktree `/workspace/.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`.

## Done

- `f3ac55dde` Unit 3: `core/branch_cleanup.py` `holds_scratch`, `_reap_name`, `_held_worktree_advice`. With scratch in the holding worktree, `cleanup_after_merge` prints `hooks-daemon worktree-reap --reap --only <name>` (directly under a sanctioned root of the main checkout) or a by-hand step (anywhere else), and no `git worktree remove`. Without scratch, the output is unchanged. It packs, removes and opens nothing. Tests: `tests/unit/core/test_branch_cleanup_held_scratch.py` (probe, link, unreadable via a monkeypatched `scandir`, bounded read, outside and nested paths, a merge run inside a linked worktree) and `tests/unit/handlers/post_tool_use/test_cleanup_after_merge.py` `TestHeldWorktreeWithScratch` (inode snapshot in act and advise; no store created; empty or absent root unchanged) plus a subprocess import test. Guidance, acceptance text and HANDLER_REFERENCE updated; `generate-docs` changed no tracked file.
- Documents commit (after `f3ac55dde`): DESIGN.md section 11 and section 13 rows; PLAN.md Task 6.2 reworded, left 🔄; niggle N691 in Plan 00474 `NIGGLES.md` (the index table does not carry N688 onward, so N691 is not indexed there either); release note `024-worktree-reap-evacuates-scratch-at-a-terminal.md`; journal entry `JOURNAL/2026-11-21/145126Z-action-b4dbd9.md`.

## Why Task 6.2 is not ticked

1. The ruling asks for one real-repository reap test per blocking verdict. Real-repository coverage exists for KEPT, live working directory, background record (both files), under minimum age and session (property test plus named tests). PROTECTED, REFERENCED, STUCK, liveness unknown, foreign owner, no birth stamp and incomplete walk are tested only at gate level (`tests/unit/core/test_worktree_scratch_evacuation.py`).
2. The ruling says `scratch-sweep status` must show an evacuated record's origin checkout. `core/scratch_store_view.py` has no checkout field, so it does not.

## QA

See the final reply for the `llm_qa.py changed` verdict.
