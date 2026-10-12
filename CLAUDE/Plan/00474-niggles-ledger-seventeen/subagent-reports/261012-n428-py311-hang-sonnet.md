# N428: the Python 3.11 CI hang

## Cause

Reproduced locally; not a deadlock in any handler or in `BoundedFifoMap`.

`tests/thread_contention.py::hammer` started 32 threads back to back with the switch interval already at 1e-9,
each calling `Barrier(32).wait()`. Under coverage, pytest-cov installs a trace function on every new thread. Python
3.11 raises `RuntimeError: Cannot install a trace function while another trace function is being installed` from
`Thread._bootstrap_inner` (its `sys.settrace(_trace_hook)` line) when two new threads call `settrace` together.
That exception is outside `Thread.run`, so the worker dies before its first line, never reaches the barrier, and
the other workers wait for ever while the main thread sits in `join()`. The stalled test is
`test_eviction_sites.py::TestFlaggableWorkAdvisorKeys::test_concurrent_recording_never_raises` (the third in the
file), which matches the CI log stopping after `test_destructive_git.py`.

## Reproduction

Python 3.11.2, coverage 7.13.5 (C tracer).

- `taskset -c 0,1 python -m pytest tests/unit/handlers/test_eviction_sites.py --cov=src`: hung past 300 s
  (faulthandler dump: 31 worker threads in `Barrier.wait`, `thread_contention.py` line 54, main in `join`).
- Same on one CPU: passed in 24 s. Same without `--cov` on two CPUs: passed twice (14 s, 20 s).
- The single test under `--cov` on two CPUs hung in roughly half the runs.
- A bare `Barrier` plus 32 threads script under `coverage run`, and a `coverage run` of the hammer outside
  pytest, did not hang (30 rounds): pytest-cov's setup is part of the trigger.
- Diagnosis: a spy plugin printed the barrier state at the hang (`count=29..31` of 32, no thread parked for the
  missing ones) and a wrapper on `Thread._bootstrap_inner` logged the `RuntimeError` above for the missing
  threads (their `run` was never entered).

## Fix

- `tests/thread_contention.py::hammer`: workers are started one at a time at the default interval, each
  confirmed running (`Event`) before the next is created; they park on `Barrier(workers + 1)`; the main thread
  then lowers the interval and releases them. Every wait is bounded by `_ARRIVAL_TIMEOUT` (60 s); a worker that
  never starts raises `AssertionError("worker N never started running")`; `start.abort()` in `finally` releases
  any parked worker.
- `tests/unit/handlers/utils/test_session_advice_counter.py` and `tests/unit/utils/test_config_cache.py` had the
  same shape (interval lowered before the threads existed, full barrier) and now use `hammer` (DRY). The
  duplicate fixture and constants were removed.
- Regression tests: `tests/unit/test_thread_contention.py` (serial start at the default interval, interval
  restored, a stillborn worker fails in about a second instead of hanging, parked workers are released, worker
  exceptions still collected).
- No new dependency; `pytest-timeout` is not installed and was not added, since the cause was found and fixed.

## Verification

- `taskset -c 0,1` with `--cov=src`: the single test 8 of 8 runs passed (before: about half hung). The whole of
  `test_eviction_sites.py`, `test_bounded_fifo_map.py`, `test_side_effect_journal.py`,
  `test_write_clobber_guard_concurrency.py` and the new test file ran twice: 66 passed each time (48 s).
- Targeted: `test_thread_contention.py`, `test_session_advice_counter.py`, `test_config_cache.py`: 33 passed under
  coverage on two CPUs.
- black `--target-version py311`, ruff and mypy are clean on the four touched files.
- Not run: the whole suite (bounded-run rule). Only a CI run on Python 3.11 can confirm the job now finishes.
- Not verified: other tests that use `threading.Barrier` with a lowered interval were not found beyond the three
  converted; `test_plan_fact_check.py` (Barrier(2)) and `test_status_message.py` (Barrier(8)) do not lower the
  interval and were left alone.

## Files

- tests/thread_contention.py
- tests/unit/test_thread_contention.py (new)
- tests/unit/handlers/utils/test_session_advice_counter.py
- tests/unit/utils/test_config_cache.py
- CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md, STATUS-INDEX.md
