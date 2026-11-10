# Plan 00579 Task 1 implementer report

Tasks 1.1 to 1.3 done on branch `worktree-579-seeded-copy-removal`.

- RED first: `tests/unit/core/test_branch_cleanup_seeded_copies.py` (real repos) failed 10 of 14 before the fix.
- GREEN: `worktree_blockers` in `core/branch_cleanup.py` now passes its surviving entries through `_judge_seeded_copies`. It reads the main checkout's `worktree_create` seed list via the new `configured_seed_entries` (`install/worktree_seed_report.py`) and compares with `seed_copy_is_identical` (`utils/worktree_seeding.py`: size check first, 64 KiB chunked read, directories need the same file set and every file identical, symlinks compare by target).
- Only copy-mode entries are excused. Diverged, missing-source, unreadable and type-mismatched copies stay blockers and read `<path> (differs from its source in the main checkout)`. No or malformed config excuses nothing.
- All three callers (`destructive_git`, `worktree_remove` handler, `clean_sweep`) get it through `worktree_blockers`. Rule text and the claude-md table in `destructive_git.py` updated.
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/030-seeded-copies-do-not-block-worktree-removal.md`.
- Extra unit tests: `tests/unit/utils/test_worktree_seed_copy_identical.py` (one test skips when run as root).
- QA: `core/branch_cleanup.py` and `destructive_git.py` are reported by `changed_tests` as unmapped `too-broad` (their reach exceeds the selection cap, as before this change); the coordinator's full gate covers them.
