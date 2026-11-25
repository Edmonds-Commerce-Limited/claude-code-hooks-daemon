# PR 251 adopt STUCK report

Interpreter: `untracked/venv-workspace-py313-ee75a947/bin/python` (no `.venv` exists in this checkout).

## Changes

- `src/claude_code_hooks_daemon/core/scratch_archive_remove.py`: `resume_claimed` returns `stuck` when no candidate verifies and an excluded record (same checkout, names the entry, other id) carries `ADOPT_PROOF`. Other excluded records still lead to `renamed-back`.
- `tests/unit/core/test_scratch_archive_remove.py`: xfail removed from the adopt STUCK test; it passes for real.
- `tests/unit/core/test_scratch_archive_apply.py`: new `test_a_crash_after_the_record_append_resumes_to_removal`. It passed on first run (the F1 fix already covered it), so it is a regression pin, not red-first. Also fixed a pre-existing mypy error (`expired_ids` imported from `scratch_archive_expire`).
- DESIGN.md adopt row: claim-id rule and STUCK outcome added. No "packed after", "earliest" or "leftover claim" wording found.
- Release note 106: one sentence for the adopt STUCK rule.
- Plan 00627 JOURNAL entry and `review-fixes-handoff-5.md`.
- PR 251 body updated (existing text kept, adopt STUCK paragraph added, ends with the Generated-with line).

## Commands and results

- `python -m pytest tests/unit/core/test_scratch_archive_remove.py tests/unit/core/test_scratch_archive_apply.py -q`: 190 passed, 3 skipped (bind mount, chattr, xz unavailable).
- `python -m pytest tests/unit/core -k scratch -q`: 1246 passed, 5 skipped (run before the apply-test import fix).
- `python -m pytest tests/unit/install/test_release_notes.py tests/integration/test_pending_release_notes_holding_area.py tests/unit/core/test_scratch_archive_apply.py tests/unit/core/test_scratch_archive_remove.py -q`: 253 passed, 3 skipped.
- black (3 files): unchanged. `ruff check`: clean. mypy on the three changed Python files: no issues.
- `scripts/qa/run_changed_tests.py --select-only --range a6b78b068~1..a6b78b068`: `scratch_archive_remove.py` maps to `test_scratch_archive_remove.py`.
- The niggles ledger has no tally needing N733 or N736.

## Not done

- No full test suite and no full QA gate (by instruction).
- The batch path (`pack_batch`) records no claim event and has no production caller; unchanged.
