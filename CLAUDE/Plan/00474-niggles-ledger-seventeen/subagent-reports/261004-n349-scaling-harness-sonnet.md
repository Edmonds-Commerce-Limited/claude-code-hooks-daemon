# N349: scaling harness divided by zero on 0-second CPU readings

Branch `worktree-n349-zdiv`, fix commit d97464d6e (based on main 5965b8bb9).

## Cause

`tests/scaling.py` `scaling_ratio` returned `large / max(small, linear_baseline_seconds(large_text))`. `small` and
the baseline are `min_cpu_seconds` readings of `time.thread_time`, which advances in ticks and can read exactly 0.0,
so the denominator could be 0.0.

## Fix

- New `clock_resolution_seconds()` (cached): spins the calling thread across two consecutive advances of
  `time.thread_time` and returns the whole tick between them (the first advance starts mid-tick and is discarded).
  If the clock does not advance twice within a 50 ms probe, it uses `time.clock_getres(CLOCK_THREAD_CPUTIME_ID)`,
  else `FALLBACK_RESOLUTION_SECONDS` (16 ms). `clock_getres` is only a fallback because a coarse clock can still
  report 1 ns.
- `scaling_ratio` now divides by `max(small, baseline, clock_resolution_seconds())`. Any nonzero CPU reading is at
  least one tick, so every case that is measurable today keeps its ratio. `SUPERLINEAR_RATIO`, `SIZE_FACTOR`,
  `REPEATS` and the measured inputs are unchanged. An unmeasurably cheap case now yields a small finite ratio.
- `counted_ratio` divides by `max(small, 1)` of an integer count: no hazard, unchanged.

## Tests

`tests/unit/test_scaling.py` (9 tests) patches the harness's `time` and `clock_resolution_seconds`: all-zero
readings (ratio 0.0, no exception), zero denominator with a measurable large run (floored at the tick), a measurable
denominator (ratio unchanged, 16.0), the baseline still flooring a tiny small cost, the resolution probe (step
measured, stuck clock falls back to `clock_getres`, then to the constant), the real clock probe, and a zero count for
`counted_ratio`.

## Results

- `tests/unit/test_scaling.py`: 9 passed.
- `tests/unit/handlers/test_safety_handlers_hostile_input_performance.py`, run once: 41 passed in 246.74 s.
- The `changed` QA result is given in the reply to the coordinator, not here, so that this file does not move HEAD
  after the run.
