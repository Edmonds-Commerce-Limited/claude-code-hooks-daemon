# N344 report: integration-test timeouts that fail under host load

Branch `worktree-n344-load`, code commit eaab931b9.

## Change

- New `tests/load_scaling.py`: `load_factor()` is the larger of the 1 and 5 minute load averages per CPU, floored at
  1 and capped at 16 (`MAX_LOAD_FACTOR`). `scaled_seconds(base)` is the idle budget times that factor. Unit tests in
  `tests/unit/test_load_scaling.py` cover the scaling, the floor, the cap, the ignored 15 minute average, an unknown
  CPU count and a host without `getloadavg`. No helper existed before (checked `tests/scaling.py`, which is a CPU-time
  ratio tool, and `tests/dispatch_timeouts.py`, fixed constants).
- `test_upgrade_pre_deploy_phase_runs_on_layer1.py`: the `git` fixture timeout (120 s), the upgrade run timeout and
  the daemon `stop` timeout (was 10 s, now a 30 s idle budget) are all scaled.
- `test_suite_passes_on_a_released_unreleased_tree.py`: the nested run timeout is scaled.
- `test_doc_truth_check.py`: idle budget raised from 60 s to 120 s and scaled (checker run and the git helper).
- `test_venv_bootstrap_driver.py`: the `_run` timeout is scaled. The watchdog test already polled, but with a fixed
  4.5 s deadline. Its build bound is now 15 s times the load stretch, and it polls until just under that bound. What it
  asserts is unchanged: no build process remains before the bound, and the log never says the bound was reached.

## Finding during verification

The first version scaled the watchdog test's deadline by the load factor. Under synthetic load (24 busy loops on 8
CPUs, `stress-ng` not installed) it failed: the process still alive was the orphaned job doing its venv work, which
took about 12 s after the KILL, and the load averages lag the real slowdown. The final version lets the bound carry
the stretch and polls up to it. It then passed at a factor of 3.3.

## N326 suggestion

Not implemented. Restricting to files changed since the last release would miss a dependency on staged content in a
test nobody touched, which is what the test exists to find. CI-only would defer the failure to release prep.

## Verification

- Idle: the four files plus the new unit tests, 86 passed; the N326 test and the watchdog class again after the final
  edit, 19 passed.
- Synthetic load (about 24 spinners, load average 26 to 33 on 8 CPUs): the watchdog class and the doc-truth file,
  19 passed. The spinners were started with `timeout` and killed afterwards.
- The upgrade file and the N326 test were not run under load (they take many minutes); their change is the same
  timeout wrapper.

## Out of scope

Other integration files with fixed `timeout=` values are untouched.
