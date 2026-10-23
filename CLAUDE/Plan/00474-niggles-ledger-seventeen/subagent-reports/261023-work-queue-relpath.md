# N533: work-queue re-brief reported a live relative worktree as MISSING

Branch `worktree-n533-work-queue-relpath`, base `5b25a1a5c`. Not merged.

## Cause

`src/claude_code_hooks_daemon/utils/work_queue.py` `_render_record` checked `Path(record.worktree).is_dir()`. A
relative recorded worktree (`untracked/worktrees/worktree-n531-child-exit`) was resolved against the daemon
process's cwd, not the project root, so a live worktree was printed as `[MISSING on disk]`.

## Fix

- `render_rebrief(records, *, now, project_root)` and `queue_briefing(path, *, now, project_root)` take a required
  project root; `_render_record` checks `(project_root / record.worktree).is_dir()`, so an absolute path is
  unchanged and a relative one is resolved under the root.
- `queue_briefing` no longer accepts `None`: the two callers gate on the queue path themselves.
- Callers: `handlers/session_start/work_queue_rebrief.py` (`_briefing`) and
  `handlers/user_prompt_submit/limit_rebrief.py` (new `_queue_lines`) each gained a `_project_root()` returning
  `ProjectContext.project_root()`, read only when a queue path exists (which itself needs a project context). No cwd
  read, no fallback.

## Tests (RED first)

RED run: 15 failures. The 13 util failures were `TypeError` on the new keyword; both handler tests failed on
`assert 'MISSING' not in ...`, which is the defect itself.

- `tests/unit/utils/test_work_queue.py`: relative worktree present under the root with the cwd elsewhere is not
  MISSING; relative worktree absent under the root (but present under the cwd) is MISSING; `queue_briefing` resolves
  against the root.
- `tests/unit/handlers/session_start/test_work_queue_rebrief.py` and
  `tests/unit/handlers/user_prompt_submit/test_limit_rebrief.py`: the same relative case end to end through each
  handler, with `monkeypatch.chdir` elsewhere.

GREEN: 98 passed across the three files.

## Ledger

N533 added to `NIGGLES.md` and `STATUS-INDEX.md` (one row, 6 pipe fields, column widths unchanged) as fixed on this
branch.

## QA

`llm_qa.py changed --range 5b25a1a5c..HEAD --allow-unmapped`: `QA: 41/41 PASSED`.

Head: see the reply (the commit that adds this report).
