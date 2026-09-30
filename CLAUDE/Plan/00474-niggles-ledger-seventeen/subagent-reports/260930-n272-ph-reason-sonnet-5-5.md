# N272: project_handlers "0 tests collected"

## Likely cause (evidence-backed)

Two timeouts nested the wrong way round. `scripts/qa/check_project_handler_tests.py`
gave `bin/hooks-daemon test-project-handlers` 300 s, but the CLI bounded its own
pytest child at `Timeout.QA_TEST_TIMEOUT` = 120 s (the mypy-sized bound, not the
pytest one). When the child is killed, the CLI prints only
`ERROR: Test execution timed out after 120 seconds` to stderr and returns 1.
pytest's output is gone, so the gate parses zero tests: "0 tests collected".

Measured here, same tree, host load average about 27 (other agents' pytest runs):
`test-project-handlers` took 82 s wall, pytest itself 69.81 s for 232 tests,
against about 4.8 s idle. That is roughly 15x slowdown, so a modestly busier host
crosses 120 s. This matches both recurrences (contention) and the passing rerun.

Not a factor: venv resolution or locks. `bin/hooks-daemon` resolves the venv
without a lock for this verb, and the `full_qa_gate` plugin is already unloaded
with `-p no:` for this run (covered by an existing test).

The defect cannot be proven to have fired on those two runs (the output was
discarded, which is the point of the diagnostic), but the 120 s bound is a
provable defect and is reachable at the measured load.

## Change

- `src/claude_code_hooks_daemon/daemon/cli.py`: pytest child bound is now
  `Timeout.QA_LONG_TIMEOUT` (300 s), the constant documented for pytest.
- `scripts/qa/check_project_handler_tests.py`:
  - outer bound is `QA_LONG_TIMEOUT + 60`, so the CLI's own timeout message is
    the one reported;
  - `build_report` adds `reason` (last 40 lines, ANSI stripped) whenever
    `total == 0`; gate errors (timeout, missing wrapper, OSError) are the whole
    output so they appear in full; the printed failure line shows it;
  - `summary.passed_all` contract unchanged.
- Tests: `tests/unit/qa/test_project_handler_test_gate.py`,
  `tests/unit/daemon/test_cli_test_project_handlers.py`.

## TDD

Red before the fix: 4 failed, 30 passed (`KeyError: 'reason'` x2,
`assert 300 > 300`, `assert 120 == 300`).
