# Task 6.2 build: handoff 1

Ruling: `/workspace/untracked/agent-reports/261121-task-6-2-ruling.md`.
Worktree: `/workspace/.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`, branch `agent-acff915e4bf3b86e6-0a26f829`.

## Done: Unit 1 (committed and pushed)

- Red first, on a real repository: `worktree-reap --reap` deleted an ignored `untracked/scratch/notes.md` along with the worktree (FileNotFoundError on the note). The data-loss route was real, including through the housekeeping step `worktree-reap-reap`.
- `daemon/cli.py` `cmd_worktree_reap`: after `ownership_refusal` and `is_reapable`, it calls `branch_cleanup.worktree_blockers` (unchanged). Any blocker prints `KEEP <name>: ...` and counts as refused, in the dry run too. New keyword seam `blockers_fn`.
- `core/branch_cleanup.py`: `_blockers_line` renamed to the public `blockers_line`; added the `WorktreeBlockersFn` alias.
- Tests: `tests/unit/daemon/test_cli_worktree_reap_ignored_content.py` (all four ruling tests plus a fixture guard). The fake-git reap tests (`test_cli_worktree_reap.py`, `_branches`, `_running_agent`, `_skipped`) pass a no-blocker `blockers_fn`.
- `--reap` help text updated. Release note added: `CLAUDE/UPGRADES/UNRELEASED/release-notes/023-worktree-reap-keeps-a-worktree-holding-ignored-content.md`.
- Journal entry filed with `mkplan.bash --journal`.

## Stopped: Unit 2, at the restore gate

`core/scratch_archive_restore.py`: `restore` sends a record whose parent is `<root>/s-*` through `_open_session(dest_parent_fd, name)`, which opens with `O_RDONLY|O_DIRECTORY|O_NOFOLLOW` and never creates the directory (lines 426-443). Once the worktree is reaped, the session directory exists in the main checkout only if the main checkout happens to have one with the same name. So a session child's archive from an evacuated worktree cannot be restored. Meeting the gate needs a change to restore's destination rules, and the ruling says to stop and hand off in that case. Nothing of Unit 2 is built.

This finding comes from reading the code. No test pins it yet. The next builder's first step should be a red test: evacuate a session child (or hand-record an archive with `original_path` `untracked/scratch/s-<x>/<name>`), then restore into a main checkout that has no `s-<x>`. Whoever owns the ruling then decides on the restore rule. Options are: create the session directory on restore, restore flat into the root, or have evacuation pack only root-level entries and keep any worktree whose scratch holds session children.

## Left

- Unit 3 (`cleanup_after_merge` prints the human command when the holding worktree has scratch). It is independent of the Unit 2 gate and not started. The ruling's Unit 3 section and tests apply unchanged.
- Documents: DESIGN.md section 11 (the "On reap" bullet and "as scratch does today") and section 13 rows (the Unit 1 finding and the evacuate gate); PLAN.md Task 6.2 rewording; `cleanup_after_merge` `get_claude_md`; HANDLER_REFERENCE. Not started.
- Targeted QA for Unit 1: the touched tests pass (288 across the reap, housekeeping, branch-defaults and branch_cleanup tests). See the final reply for the `llm_qa.py changed` result.
