# N462 implementer report: combinatorial-growth performance test flake

## Assumptions and the one result that is not what the brief asked for

- The brief's proof 2 (pass count before and after under host load) could NOT be produced as asked: the flake did not
  reproduce on this host under real load, before the change. I ran two load profiles against the two named tests
  (`..._on_a_deep_write_path[.ts]` and `test_bash_command[nested_braces]`; plus all five deep-path suffixes in the
  first profile) with 16 burner processes on 8 cores:
  - CPU spinners, six runs of the 6-test selection: 6 pass, 0 fail (before).
  - Memory-thrashing burners (1 MiB bytearray churn), eight runs of the 2-test selection: 8 pass, 0 fail (before),
    8 pass, 0 fail (after).
    So the real-load before/after counts are 8/8 and 8/8: they show no regression and unchanged runtime (before 43-53 s
    per run, after 45-57 s), not an improvement. I am not claiming real-load evidence of the fix.
- Instead I proved the mechanism with a synthetic harness (`untracked/scratch/noise_harness.py`, not committed): a
  linear work function whose cost is inflated 30x for five consecutive runs, started with probability 0.03 per run,
  fed to the real `scaling_ratio`. Old `tests/scaling.py`: 15 false positives in 60 trials (max ratio 58.7). New:
  0 in 60 (max 23.9). Same seed.
- Assumption: the brief says "mark N462 done only if both proofs hold". Proof 1 (planted regression) holds. Proof 2
  holds only in the synthetic form above. I took the conservative reading and did NOT mark N462 done: NIGGLES.md
  records the fix commit but keeps Status ⬜ Open, and STATUS-INDEX.md is unchanged. The coordinator can rule the
  synthetic proof sufficient and flip it, or wait for the next full QA gate to show the file passing.

## Root cause

`tests/scaling.py` already took minimums and floored the denominator. What it left asymmetric: the small side is
sampled until 10 ms of CPU is spent (up to 40 runs), so its minimum is very clean; the large side of any heavy case
(deep write paths: tens of ms to seconds per run) gets exactly `REPEATS` = 3 runs. One stall that outlasts those three
consecutive runs makes the large minimum 3-30x too high while the small minimum stays clean, and the ratio crosses 24.
That also explains why the failing handler differs each run: the stall lands on whichever handler is being timed.

## Change (`tests/scaling.py`)

`scaling_ratio` now treats an over-threshold ratio as suspect: up to `CONFIRMATION_ROUNDS` (4) further rounds measure
both sides again and pool the minimums with the earlier ones. It stops as soon as the ratio is at or under
`SUPERLINEAR_RATIO`. The threshold is unchanged. A clean handler pays nothing extra (the ratio is under threshold
after round one), so file runtime is unchanged; only a suspect handler pays for re-measurement. Noise only adds
time, so pooling minimums is sound; a handler that really is superlinear is over the threshold in every round.

## TDD (red output)

New tests in `tests/unit/test_scaling.py`, class `TestScalingRatioConfirmsAnOverThresholdReading`, written first:

```
FAILED tests/unit/test_scaling.py::TestScalingRatioConfirmsAnOverThresholdReading::test_a_cost_that_stays_high_in_every_round_stays_flagged - AttributeError: module 'tests.scaling' has no attribute 'CONFIRMATION_ROUNDS'
3 failed, 1 passed, 12 deselected
```

After the change: 15 passed (I also dropped a fourth draft test whose premise was wrong: a lucky-LOW small reading is a
legitimate minimum, not noise, and is bounded by the baseline floor).

## Proof 1: planted regression

A temporary test file (deleted, never committed) subclassed the deep-path sweep and monkeypatched
`TddEnforcementHandler.handle` to rescan the tail of the serialized input for every character (quadratic). With the
confirmation rounds in place:

```
TddEnforcementHandler cost grew 32x for 8x input in path depth on .ts
1 failed, 7 deselected
```

The existing `TestTheSweepMeasureSeparatesLinearFromQuadraticHandlers` (exponent-2 handler flagged, exponent-1 not)
also still passes.

## Runtime

Whole `test_safety_handlers_hostile_input_performance.py` plus `test_scaling.py`: 58 passed in 281.8 s after the
change. Before the change the hostile-input file alone took 5 m 20 s (320 s) in isolation, on a shared host. Same or
lower.

## Commits

- `50a3537ee` the scaling change and its unit tests.
- The ledger, status-index and this report are in the follow-up commit.

## Final QA verdict (branch head b8eff2b69)

`llm_qa.py changed --allow-unmapped`: QA: 37/40 PASSED, 1/40 FAILED, 2/40 NOT MEANINGFUL, exit 1. The single failure is
a plan_qa journal-freshness advisory about Plan 00472 (journal quiet for 4 days), not this plan. The two
NOT MEANINGFUL entries (project_handlers, changed_tests: 1997 passed, 0 failed) are only so marked because the plan_qa
detector failed. Nothing of N462's own failed.
