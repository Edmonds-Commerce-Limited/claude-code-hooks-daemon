# N279: changed_tests with zero executed tests

Fix: `scripts/qa/run_changed_tests.py` `build_report` now sets `summary.error` when test files were selected and pytest executed none: pytest's exit code, the number of files selected and the last 15 lines of output. `llm_qa.py` already prints `summary.error`, so the red line carries the reason. An empty selection is unchanged.

Finding: the verdict already failed (`total > 0` has been part of `tests_green` since Plan 00463); the defect was a reasonless `0 passed, 0 failed, 0 skipped` line.

Ruled out: pytest timeout (starts after the lock), gate refusal (exit 1, no summary, fails; 50 files is 4% against a 25% threshold), lock wait changing the child (lock is taken before any tool). Not found: why the original run executed zero tests; its report was overwritten.

Tests: `TestSelectedButExecutedNothing` in `tests/unit/qa/test_run_changed_tests.py` (8 red before, green after); 139 passed with `test_llm_qa_changed.py`.

Not verified: pyright cannot resolve `pytest` in the worktree venv (environment); mypy reports 2 existing `no-any-return` errors at lines 92 and 866 of the test file, not from this change; no full suite or `llm_qa.py all` run.
