# Phase 5 handoff 6 (Tasks 5.5 and 5.7 done; Phase 6 not started)

## Done

- Task 5.5: `core/scratch_archive_apply.py` gains `Pressure` and `pressure_for(level, caps, ttl_hours)` (None below
  block or for a root with no TTL). `ApplySettings.pressure`; `_actionable(row, pressure)` also admits a not-due,
  walk-complete DISPOSABLE/UNCERTAIN row whose `age_hours >= idle_hours`; rows run due-first, then largest
  `directories` first (`_pressure_order`); `_record` adds `ttl_hours - age_hours` to a pressured archive's hold.
  `daemon/cli.py` `_scratch_pressure` reads the cached inventory (missing/unreadable: no pressure) and prints a note
  to stderr when pressure is on. TTY gate untouched. Tests: `TestPressureMode`, `TestPressureFor` in
  `tests/unit/core/test_scratch_archive_apply.py`.
- Task 5.7: `daemon/housekeeping.py` report steps `scratch-sweep` and `scratch-sweep-apply` (advisory, argv
  `scratch-sweep`, no `--apply`), Decision 6 docstring amended; DESIGN section 10 row and PLAN say the step becomes
  the unconfirmed mutating step only when the owner removes the TTY gate. Test: `TestScratchSweepSteps`.

## Next

- Task 6.1: sweep every registered worktree's scratch root; limit a sub-agent's `--apply` to its own checkout. Not
  started.
- `tests/unit/daemon/test_cli_scratch_*.py` pass with the cli.py wiring, but `_scratch_pressure` has no direct test
  (a CLI test with an inventory at block would cover it).
