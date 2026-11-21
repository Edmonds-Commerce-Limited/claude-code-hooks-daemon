# Phase 5 handoff 1 (Step 0 and Task 5.3 done; 5.1 and 5.2 not started)

Branch `agent-acff915e4bf3b86e6-0a26f829`, origin/main merged.

## Done

- b04bc7623: the mypy error at `tests/unit/core/test_scratch_archive_apply.py:479`. Cause: the test raised `apply_mod.RemoveRefused`, which `scratch_archive_apply` imports but does not re-export (no-implicit-reexport). The test now imports it from `scratch_archive_remove`. The red-first evidence for e3b268211 is in the journal entry `JOURNAL/2026-11-21/035930Z-finding-c72b15.md`: a behavioural red (3 keep tests) with only the `_session_kept` term removed, and a red on the not-a-directory test with the `scratch_sweep.py` hunk reverted.
- e8f8940d3, Task 5.3: `src/claude_code_hooks_daemon/core/scratch_caps.py` with `evaluate_caps(counts, caps, *, incomplete, previous=None, index_directories=None, index_cap=None) -> CapReport` (`CapLevel` is an IntEnum: OK/WARN/BLOCK). An incomplete inventory raises the level to at least `previous`. `mode: advise` keeps the level and sets `enforce=False`, and `off` evaluates nothing. Tests in `tests/unit/core/test_scratch_caps.py`: 14 pass, and ruff, black, mypy and pyright are clean.

## Next (not started)

- **Task 5.1**: `untracked/scratch-inventory.json`, holding per entry the directories, files, bytes, newest mtime and verdict hint, plus `incomplete`, `generated_at` and the last `CapLevel`, which is what feeds `previous`. Write it atomically (temp file and rename). Refresh it in a background thread at SessionStart, after a Bash command that creates directories under a scratch root, and at the end of every `scratch-sweep` run. A hook only ever reads the file. Build it from the existing `scratch_sweep` report or walk, and do not walk again.
- **Task 5.2**: extend the existing SessionStart handler `handlers/session_start/scratch_sweep.py` (from Task 4.1, which creates the session directory) so it does not duplicate. Order it directly after `branch_sweep` (check `branch_sweep`'s priority). Read only the inventory. Print the counts by verdict, the overdue-to-file list, archives about to expire with their restore commands, and the caps from `evaluate_caps`. Stay silent when clean. Always speak when the inventory is incomplete, missing or stale. Follow CLAUDE/HANDLER_DEVELOPMENT.md for the config, the acceptance tests and the docs.
- Tooling: run mypy as `MYPYPATH=src /workspace/untracked/venv-workspace-py313-0d6d49c6/bin/mypy <files>` from the worktree. Without MYPYPATH it type-checks main's editable install. pytest needs `PYTHONPATH=src`.
