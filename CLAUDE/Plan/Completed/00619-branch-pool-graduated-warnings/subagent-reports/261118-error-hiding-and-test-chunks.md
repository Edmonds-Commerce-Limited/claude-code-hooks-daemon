# Error-hiding fix and ladder test chunks

## 1. error_hiding (return-none-on-error)

`try_pool_pressures` in `src/claude_code_hooks_daemon/core/branch_ladder.py` now returns a frozen `PoolReading(pressures: tuple[PoolPressure, ...] = (), unreadable: bool = False)`. A failed read (any exception) is logged via `log_and_continue` and returned as `PoolReading(unreadable=True)`; it never raises and never denies, strict mode or not.

Callers updated: `pool_pressures` (returns `list(reading.pressures)`, empty when unreadable) and `PressureCache.get` (uses `reading.unreadable` to choose the failure TTL). No other caller in `src/` or `tests/` used the function directly beyond the cache-counting wrapper in `tests/unit/core/test_branch_ladder.py`, which passes the reading through unchanged.

Test first: commit f7d35d5f7 (RED: `TestTypedReading` in `tests/unit/core/test_branch_ladder_fail_open.py`, 2 failed), then commit 1f95e84d2 (GREEN). All existing fail-open tests still pass (67 passed across the fail-open and ladder core test files). `python3 scripts/qa/audit_error_hiding.py` reports no violations; mypy on the module is clean. Both commits are pushed on the branch.

## 2. Test chunks (64 files: the test diff from c946dc3e7000 plus ladder, creation, sweep, stop, registration, reference and config-model tests)

The worktree has no venv; `HOOKS_DAEMON_VENV_PATH` pointed at the shared venv with `PYTHONPATH` set to this worktree's `src`; the import check resolved to this worktree's `src`.

| Chunk | Files | Result                |
| ----- | ----- | --------------------- |
| 00    | 25    | 1672 passed, 0 failed |
| 01    | 25    | 858 passed, 0 failed  |
| 02    | 14    | 335 passed, 0 failed  |

No real failures, so no further fixes were needed. The 1800 s `changed_tests` gate was not rerun.
