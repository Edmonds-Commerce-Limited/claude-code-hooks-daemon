# Perf sweep failure on PR 243: diagnosis

Test: `test_many_appends_each_run_are_judged_quickly` (limit `scaled_cpu_seconds(1.5)`), CI measured 1.57 s (115.461 - 113.888) in the log. The CI job ran 17 perf_sweep tests in 85.8 s.

## Local measurements (PR worktree, PYTHONPATH=src, `-m perf_sweep`, 5 runs)

Call time: 0.23, 0.21, 0.19, 0.19, 0.23 s (about 0.2 s). Whole-run 0.68-1.30 s. The limit is 1.5 s, so local headroom is about 7x.

## Cause

(b) is the better fit, but not proven. The PR diff (15 files: new session_start `coordinator_board` handler, constants, config, docs, tests) does not touch `subagent_full_qa_blocker.py` or anything it imports. The last main change to that file was 2026-11-10 (cc6ace282, afc1debf8), before PR 239 passed the same job. No evidence of a code regression.

CI is about 7x slower than local for this test. In the 2026-11-24 run the test body takes 1.57 s against a 1.5 s bound. That points to a slow or loaded runner with a bound that sits too close to the measured time. The scaling in `scaled_cpu_seconds` was not read; the grep was blocked by hook guidance, so the scaling factor and CI env are unverified.

## Recommendation

1. Rerun the job. Two runs failed at near-identical 1.55-1.57 s, so a consistent slow runner is likely, not noise.
2. If it keeps failing, loosen the bound test-first to a justified value (for example 3 s, which is about 15x local and still catches the quadratic blow-up this test guards against). Alternatively check what `scaled_cpu_seconds` multiplies by in CI.
3. Do not treat it as a regression from PR 243.
