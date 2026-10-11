# Plan 00500 Task 1.1: where the full QA gate spends its time

Analysis only; no code or config changed. Probes ran one at a time with the checkout venv (py3.11, `untracked/venv-workspace-py311-81c29529`), `--no-cov -p no:randomly -p no:cacheprovider`. The host was loaded (load 8-10 on 8 cores) by the live gate throughout, so probe durations are inflated by an unknown factor. Treat ratios as sound and absolute values as upper bounds. All durations below are in seconds.

## 1. Step list and order

`llm_qa.py all` runs `ALL_TOOL_NAMES` (`scripts/qa/llm_qa.py:815`, registry `:557-810`) strictly serially (`_run_tools`, `llm_qa.py:2644` `for name in tools`; `run_tool` is a blocking `subprocess.run` with stdout/stderr to DEVNULL, `:1385`). Order: magic_values, format, lint, type_check, pyright, **tests**, security, dependencies, shell_check, about 30 `check_*` scripts, semgrep, capture_corruption, repo_hygiene, doc_truth, doc_snippets, plan_qa, docs_qa, sensitive_content, git_history, handler_reference, generated_doc_drift, british_english, project_handlers, hook_contract, input_contract, smoke_test (last). `changed_tests` is excluded from `all` (`:813`).

`tests` is `run_test_matrix.py` (`llm_qa.py:595`). The CI matrix is 3.11/3.12/3.13 (`.github/workflows/qa.yml:200`); the primary here is 3.11. The plan (`run_test_matrix.py:183-189`):

- Phase 1, concurrent: py3.11 FULL `tests/` via `run_tests.sh` with `--cov --cov-branch`, plus py3.12 `tests/unit` and py3.13 `tests/unit`. Each is one single-core pytest process (no xdist).
- Phase 2, serial (`:254-267`): py3.12 `rest`, then py3.13 `rest` (`tests --ignore=tests/unit`), one at a time because the acceptance tests drive the one live daemon. Phase 2 does not start until every Phase 1 job has ended (`:250-252`), so it waits for the py3.11 coverage run.

Test body executions per gate: 42,860 (py3.11 full) + 2 x 35,897 (unit) + 2 x 6,963 (rest), about 128,600, three times the suite. The extras repeat every `tests/unit/qa/` test that itself re-runs ruff/bandit/semgrep/real repo scans (section 2).

Serial today but independent: all non-test checks run one after another around the `tests` step, never alongside it (pyright, semgrep, shell_check, security_downgrade_flags, project_handlers and the doc checks are self-contained). Phase 2's two legs are serial by design but are hermetic apart from `tests/acceptance` (96 tests) and the daemon-driving tests.

## 2. Measured hot spots

Collected (`pytest --collect-only`, 65 s, 42,860 items): unit 35,897 (handlers 13,904; utils 6,529; core 2,651; daemon 2,624; strategies 1,703; install 1,688; qa 1,470; supervise 1,325), integration 6,299 (one file, `test_no_root_conditioned_skips.py`, holds 1,587), config 257, daemon 198, acceptance 96, other 56. Source files using subprocess: unit 200, integration 146. `time.sleep(` calls: unit 43, integration 40, acceptance 2. Files creating git repos: unit 42, integration 20.

Per-test durations from probes:

| Probe                                                                                                                                                                                                                                      | Tests | Wall (s) | Average per test (ms) |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----- | -------- | --------------------- |
| `tests/integration/test_no_root_conditioned_skips.py`                                                                                                                                                                                      | 1,587 | 53.7     | 34                    |
| 7 integration files (`ordinary_command_regression_gate`, `init_sh_pretooluse_fail_closed`, `venv_bootstrap_driver`, `init_sh_needs_provision`, `claude_md_guidance_coverage`, `generated_docs_are_path_agnostic`, `handler_instantiation`) | 1,704 | 315      | 185                   |
| `tests/unit/daemon` + `tests/unit/qa`                                                                                                                                                                                                      | 4,102 | 865      | 211                   |

Slowest individual tests:

- `tests/integration/test_venv_bootstrap_driver.py`: 31.8 (`test_a_killed_build_process_takes_its_watchdog_with_it`), then 9.6, 9.1, 7.2, 7.1, 6.2, 5.8. This file is about 140 of the 315 sampled: real detached builds and watchdog waits.
- `tests/integration/test_init_sh_pretooluse_fail_closed.py`: 8.6, 5.1, 4.2, 3.9 (real `init.sh` spawns and poll deadlines).
- `tests/unit/qa/test_run_test_matrix.py::TestThePluginLoadsAfterCoverageStarts`, two tests: 47.6 and 46.5 (each runs a nested pytest under coverage).
- `tests/unit/qa/test_glob_readers_are_declared.py`: 8 tests at 20-24 each, about 175 in total (repo-wide scans repeated per parameter, no shared cache).
- `tests/unit/qa/test_llm_qa_main_moved.py`: a 22.5 setup plus a 6.0 test.
- `test_run_semgrep_check` 13.9 and 8.9; `test_audit_error_hiding` 8.0 and 7.8; `test_run_dependency_check` 7.2 and 5.7; `test_run_security_check` four tests of 5.7-6.1; `test_run_format_check` 6.7 and 5.9; `test_run_lint` 5.7.
- The top 25 in unit/qa total about 450 of the 865. The `tests/unit/qa/test_run_*.py` files re-execute the gate's own tools (ruff, bandit, deptry, semgrep) as subprocesses against the real repo, so each interpreter repeats work the gate already does in its non-test steps.
- `test_no_root_conditioned_skips.py`: the `test_no_root_conditioned_skip_exists[<file>]` cases cost 0.2-0.5 per call (1,587 cases); each re-reads and re-parses per file.

Patterns found: real subprocess spawns (daemon, git, bash `init.sh`, bandit/semgrep/ruff), sleeps and deadlines polled in the venv-bootstrap and init.sh tests, repo-wide scans repeated per parametrization, nested pytest runs. No venv or repo-building fixture dominates apart from the venv bootstrap driver tests. The per-test autouse `no_test_writes_tracked_generated_docs` (`tests/conftest.py`, around `:600-680`) reads and stats the protected files and the daemon pid file for every one of the 42,860 tests; its cost was not measured.

Coarse step durations from file mtimes (gap between consecutive result files; runs were interleaved, so approximate):

- Live worktree, current run (started after the host reboot; uptime 5 minutes at 13:26): magic_values written 13:24:46, format 13:25:47 (61), lint 13:25:54 (6.6), type_check 13:26:02 (8).
- Live worktree, previous run killed by the reboot: type_check 11:47:51, pyright 11:50:57 (**186**), tests started about 11:52:58. The py3.13 unit leg last wrote its log at 12:26:22 and py3.12 unit at 12:28:01, so each extra unit leg ran about 2,000 while sharing the host with the primary. The primary `tests.json.raw` was still growing at 13:19:41 (over 5,200 in, unfinished); no `rest` logs exist because Phase 2 never started. The reboot ended it.
- Worktree 10-06 `changed` run (13:36:40 to 13:45:42, 542 of static checks): shell_check 72, signal_targets 48, project_handlers 38, security 38, docs_qa 29, sensitive_content 17, semgrep 117, changed_tests 110.
- `/workspace/untracked/qa`, 10-03 full run: pyright 101. Unit extras ended 08:22:41 (3.13) and 08:24:04 (3.12), about 1,200 after pyright. `tests-py3.12-rest.log` ended 09:55:30 and `tests-py3.13-rest.log` 10:23:48, so each serial Phase 2 leg is about 1,700, which puts the end of the primary near 09:27, about 5,000 after Phase 1 began (inferred, not measured). The post-test static checks then ran 10:24:09 to 10:31:15, about 420 in total: security_downgrade_flags 71, project_handlers 53, capture_corruption 47, canonical_callers 25, shell_check 24, signal_targets 20, plan_qa 88 (gap), smoke_test 13.
- 10-06 full run: 42,314 tests, coverage 95.39 percent, `coverage.json` written 06:19:40; the previous result file was 03:52, so a coverage run can take up to about 8,500 on this host (loaded-host caveat).

In short: `tests` is roughly 90 percent of the gate (primary run over 5,000, then Phase 2 about 3,400 serial). The static checks total about 600-900; the biggest are pyright (100-186), semgrep (117), plan_qa/docs_qa, shell_check, security_downgrade_flags.

## 3. Timing recorded today (exact), and what is missing

- Recorded: only `duration_seconds` per interpreter-matrix leg and `wall_seconds`, in `tests.json` `.interpreters[]` (`run_test_matrix.py:121-127` RunResult; `:300` entry; `:350` `wall_seconds`; printed `:583-597`). The 10-03 and 10-06 `tests.json` files in `/workspace/untracked/qa` carry no `interpreters` key (the 10-06 file is the primary-only `run_tests.sh` output), so no leg duration survives there.
- Not recorded: any `llm_qa.py` step duration (nothing wraps `run_tool` at `llm_qa.py:2666`; output goes to DEVNULL at `:1385-1392`); start or end stamps in `provenance.json` (a record holds only head, tree_digest, passed, exit_code, output_sha256; `llm_qa.py:371-520`); per-file pytest timing.
- Per-test `duration` is wired at `run_tests.sh:116-122` but only on the `pytest_json_report` branch (`:72`). The plugin is in no venv (site-packages has pytest 9.0.3, pytest-cov 7.1.0, pytest-mock 3.15.1; no json-report, xdist, randomly or timeout), so the text-fallback branch runs (`:147-246`) and records only failures (`:197`). No `--durations` appears in `addopts` or any script. The extras' logs hold no per-test durations either.
- `provenance.json` is written once, AFTER the whole loop (`_record_run`, `llm_qa.py:2683`). A killed run records nothing, which is what the reboots did.
- In `/workspace/untracked/qa/provenance.json`, 28 of the 41 records carry `tree_digest: "changed-during-run"` (`llm_qa.py:2576-2579`: one before/after comparison for the whole run), so `--read-only` reads them stale and they could not serve as checkpoints.

## 4. Ranked recommendations

Ranked by payoff against size of change and risk.

1. **Per-step timing summary.** Wrap `run_tool` (`llm_qa.py:2666`) in `time.monotonic`; store `started_at`, `ended_at`, `duration_seconds` on each provenance record; print a sorted table at the end of `_run_tools`; also print the matrix legs' durations. Saves nothing itself but makes everything else measurable. Small change (one function plus a unit test in `tests/unit/qa/`). Risk: none.
2. **Per-test and per-file durations.** Add `--durations=50` to `extra_pytest_argv` (`run_test_matrix.py:502`) and to both pytest calls in `run_tests.sh`, and save the parsed slowest list into `tests.json`. Alternative: add `pytest-json-report` to the dev extras and `uv.lock`, which activates the existing `:116-122` code. `--durations` is lower risk (no new dependency, works in the text branch). Risk: none.
3. **Write each step's record as it finishes, then add `llm_qa.py all --resume`.** Move `record_provenance` into the loop with a per-step before/after tree check (fixes the whole-run `changed-during-run` digest); `--resume` runs only tools whose record fails `stale_reason` (`:440`), reusing the `--read-only` branch (`:2650-2656`). Recovers the whole static tail (600-900 measured) after a reboot. Medium change. Risk low as long as a stale or missing record always means "run it again".
4. **Resumable test shards.** Record each of `3.11-full`, `3.12-unit`, `3.12-rest`, `3.13-unit`, `3.13-rest` on completion, so a reboot repeats at most one shard. The primary 3.11 run is the largest unit (over 5,000), so it needs its own split, for example per top-level directory. Coverage must stay whole-suite (`pyproject.toml:147` `fail_under = 95.0`) and `parallel` is disabled (`:135-136`), so sharded coverage needs per-shard `COVERAGE_FILE` plus `coverage combine`; the extras need no coverage at all. No speed gain by itself, but caps a reboot's loss to one shard. Medium to large change; risk medium (coverage combine).
5. **Cut the slowest tests** (about 25 tests, 600-1,000 per interpreter, so up to roughly 1,800-3,000 per gate across three interpreters): a module-scoped cache for the repo scans in `test_glob_readers_are_declared.py` (8 x 20-24) and `test_llm_qa_main_moved.py` (22 setup); parse the tree once in `test_no_root_conditioned_skips.py`; shrink the two 47 nested-pytest tests in `test_run_test_matrix.py`; inject the clock or bounds in `test_venv_bootstrap_driver.py` (31.8 watchdog test; about 140 for the file) instead of waiting. Assertions unchanged, only cost changes. Medium change; risk low (re-run each file).
6. **Run independent non-test checks alongside `tests`** (bounded pool of 3-4; `tests` and `smoke_test` stay in their own lanes because they need the live daemon). Each tool writes its own `json_file`, so there is no output collision. CPU is already contended (three pytest processes on 8 cores), so the gain is mainly the I/O- and subprocess-heavy checks, bounded by the 600-900 static tail. Medium change; risk low to medium.
7. **Do not repeat self-scan tests on every interpreter.** The `tests/unit/qa/test_run_*.py` and glob-reader scans do not depend on the interpreter; running them on the primary only would cut the extras. It narrows what the gate runs per interpreter (a Non-Goal unless the tests are provably interpreter-independent), so it needs the owner's decision.
8. **Evaluate pytest-xdist** (largest potential payoff, riskiest). Findings:
   - Not installed. `src/claude_code_hooks_daemon/qa/full_qa_gate.py:21-30` says xdist is untested with the sink: workers are exempt (`_is_xdist_worker`, `:52-54`) but the controller may not see the whole item list. The lock descriptor travels by `pass_fds` (`run_test_matrix.py:541`, `llm_qa.py:1391`); execnet spawns workers with `subprocess`, which closes inherited descriptors, so the lock proof may fail in workers.
   - Shared state: the autouse `no_test_writes_tracked_generated_docs` compares the protected repo files and the daemon pid file per test; a legitimate write by another worker would trip it.
   - The live daemon is shared by `tests/acceptance` (96 tests) and the daemon-driving integration tests (`run_test_matrix.py:16-20`); they must stay in one non-parallel group.
   - 25 test files `chdir`; 207 touch `untracked/`; 127 use literal `/tmp/` paths (cross-worker collision risk). No fixed TCP ports (0 matches). 827 files use `tmp_path` (safe per worker).
   - Coverage: `parallel` is disabled for a fork-bomb reason (`pyproject.toml:135-136`); pytest-cov handles worker data under xdist, but this needs proof here.
   - Safe first trial: `-n 2` or `-n 3` on `tests/unit` for the extras only (hermetic, no coverage), measure, and keep `tests/integration` and `tests/acceptance` serial.

## Files read or sampled

`scripts/qa/llm_qa.py`, `scripts/qa/run_test_matrix.py`, `scripts/qa/run_tests.sh`, `tests/conftest.py`, `pyproject.toml`, `src/claude_code_hooks_daemon/qa/full_qa_gate.py`, `/workspace/untracked/qa/*`, the live worktree's `untracked/qa/*` (read only), probe outputs in `/workspace/untracked/scratch/` (`collect.txt`, `d1.txt`, `d2.txt`, `d3.txt`).
