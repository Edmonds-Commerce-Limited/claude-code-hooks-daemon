# Plan 00500: full qa timing and speed

**Status**: In Progress
**Created**: 2026-10-07
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The full QA gate (`./scripts/qa/llm_qa.py all`) has grown large and slow. On 2026-10-07 one run of it on a work branch
took more than 90 minutes, its tests reaching 15% an hour after they started, and host reboots killed five runs in a
row before one finished. Every reboot sends the gate back to the top, so a release waits on a run that the host keeps
interrupting.

Two things are missing. First, timing: only the Python-version matrix legs record a duration
(`scripts/qa/run_test_matrix.py:126`), so nobody can see which step costs the time. Per-test durations are wired in
`scripts/qa/run_tests.sh:116-122`, but only on the pytest-json-report branch, and that plugin is not installed, so they
are never recorded. Second, resumability: each step's result is already tied to the tree it ran on (`provenance.json`,
`llm_qa.py:371-520`), and `--read-only` already rejects a stale one, but there is no mode that re-runs only the stale
steps, so an interrupted run starts again from the top. The test matrix already splits the suite into `unit` and `rest`
scopes and runs the interpreters concurrently (`run_test_matrix.py:69-79`); the tool loop in `llm_qa.py` is serial, and
pytest-xdist is not installed, so each test leg runs on one core.

This plan adds timing first, measures the hot spots from it, then makes the gate resumable and faster.

## Goals

- Every gate step records its wall-clock time, and the gate prints a per-step timing summary at the end.
- The test step records per-file and per-test durations, with the slowest listed in the report.
- An interrupted gate resumes from a checkpoint: a step whose passing result was recorded for the exact same tree is
  not run again.
- The full gate's wall-clock time drops measurably, with the savings measured, not estimated.

## Non-Goals

- Weakening any check, lowering the coverage threshold, or skipping tests to save time.
- Changing what the gate verifies; only how it is scheduled and recorded.

## Tasks

### Phase 1: Timing

- [x] ✅ **Task 1.1**: Read-only review of where the time goes and of today's timing data. Report:
  [subagent-reports/261007-qa-speed-review-sonnet.md](subagent-reports/261007-qa-speed-review-sonnet.md). The test
  body runs about three times per gate (3.11 full with coverage, then 3.12 and 3.13 in unit and rest scopes) and is
  about 90% of the gate; the slowest tests are unit/qa tests that re-run ruff, bandit and semgrep over the repository.
  For resume, `provenance.json` is written once after the whole loop, so a killed run records nothing.
- [x] ✅ **Task 1.2** (merge `ae92258cf`): Record each gate step's start, end and duration in its result file, and print a sorted per-step
  timing summary at the end of `llm_qa.py all` (TDD).
- [x] ✅ **Task 1.3** (merge `0c4b9a168`): Make the dormant per-test durations real (install pytest-json-report through
  `uv.lock`, or pass `--durations`) and surface the slowest test files and tests in the report. Done with
  `--durations=50 --durations-min=1.0` on every pytest leg; each leg's `slowest_tests` lands in `tests.json` and the
  tests summary lists the top 10 across legs.

### Phase 2: Checkpoints and resume

- [x] ✅ **Task 2.1**: Confirm the existing provenance (`scripts/qa/llm_qa.py`: `worktree_state`, `stale_reason`,
  `read_provenance`, `record_provenance`) is enough to key a checkpoint: every step,
  including each matrix leg, records the tree it ran on, so a stale result can never be taken as a pass. Confirmed by
  building on it: Task 2.2 keys each step's record to the tree before and after it, and Tasks 2.3 and 2.4 key each leg
  and shard checkpoint with the same `worktree_state` and `stale_reason`.
- [x] ✅ **Task 2.2** (merge `4d8427ea4`): Write each step's provenance record as the step finishes, with its own tree check (before
  this task the file was written once after the whole loop), then a resume mode (`all --resume`) that skips steps whose
  passing result matches the current tree and runs the rest.
- [x] ✅ **Task 2.3** (merge `89f8f722e`): Give each matrix leg and scope (`unit`, `rest`) its own checkpoint, so a reboot mid-tests loses
  only the leg it interrupted, while coverage is still judged on the whole (parallel coverage mode is disabled today,
  `pyproject.toml:135-136`).
- [x] ✅ **Task 2.4** (merge `7c86303cd`): Shard the test suite. Split each leg into named shards (by test directory, balanced with the
  per-test durations from Task 1.3), each a Task 2.3 checkpoint of its own, so a reboot loses one shard rather than a
  whole leg. Coverage: each shard writes its own data file (`COVERAGE_FILE`, no `--cov-fail-under`), kept with its
  checkpoint; `coverage combine` then `coverage report --fail-under=95` judges the whole, so the threshold is unchanged.
  This needs no `parallel = true` in the coverage config (disabled for a fork bomb). Running shards concurrently is
  Task 3.2's question (the shared daemon, the full-QA lock and its sink plugin) and is not assumed here. For WIP QA,
  untouched tests are already skipped by `llm_qa.py changed` (`scripts/qa/run_changed_tests.py`); shards (`scripts/qa/test_shards.yaml`) now exist, and
  narrowing its unmapped and too-broad fallback, which today runs the whole suite, to the shards the change can
  reach was the follow-up, Task 2.5, which measurement declined.
- [x] ❌ **Task 2.5**: `llm_qa.py changed` narrows its unmapped and too-broad fallback to the shards a change can reach
  (`scripts/qa/changed_shard_reach.yaml`, `qa/shard_reach.py`), the follow-up Task 2.4 named. **DECLINED WITH EVIDENCE:
  the fallback stays the whole suite, as on main.** A first build reached one import hop, which review round 1 showed
  under-selects (a hub's real tests sit several imports away). Sound reach follows the full import chain (the transitive
  closure of reverse imports, package `__init__.py` included). Measured over every one of the 3,770 tracked non-test
  files against the 1,423 test files: of the 2,833 that main sends to the whole suite, 2,816 still reach every shard
  and only 17 (0.6%) narrow; of the 272 Python ones, 17 (6%), and those are near-empty package `__init__.py` files and
  test-local conftests. The mean fraction of the suite selected is 0.996 for the files that fall back (0.956 for the
  Python ones), so narrowing saves under 10% of the tests for nearly every file it could touch. The selector, the
  declaration and their tests were removed rather than shipped for that margin. The earlier "only ever wider" claim
  was true only after the closure, which is what removed the saving. The `whole_suite` trigger bug (B3) existed only in
  that build: main has no such list.

### Phase 3: Speed

- [x] ✅ **Task 3.1** (merge `c02cf9838`): Act on the measured hot spots: the slowest tests, steps that can run
  concurrently, any duplicated work such as repeated matrix legs. Done. Times are per leg: "after" was measured on a loaded host, and "before" also, except where only the last full
  gate's figure existed:

  - The released-tree readers test went from 520 s to 172 s; its 25 readers now run as four concurrent nested runs,
    and every group's failure is reported.
  - The layer-1 upgrade file went from about 380 s to 166 s; its origin repository is built once per module.
  - `test_gate_fires_when_the_cache_cannot_hit` went from 129 s to 11 s. The resolver's probe watchdog held the
    caller's pipe for its whole bound. That is a fix in client-run `scripts/lib/resolve_venv.sh`: stdio is detached and
    the watchdog kills its own `sleep`.
  - The glob-reader guard went from several hundred seconds to 29 s, by building its scans once.
  - Three hot spots were declined with reasons: the signal checker scan, the main-moved fixture, and the hostile-input
    timing that is itself the measurement.

  Reports: [subagent-reports/261009-task-3.1-hot-spots-sonnet.md](subagent-reports/261009-task-3.1-hot-spots-sonnet.md)
  and the two reviews beside it.

- [x] ❌ **Task 3.2**: Evaluate pytest-xdist (running tests across cores): whether the suite is safe in parallel
  (sockets, ports, working directory, the full-QA lock and its sink plugin), and adopt it if it is.
  **DECLINED WITH EVIDENCE** (merge `232d1772e`, [report](subagent-reports/261010-task-3.2-xdist-sonnet.md)), on an
  8-CPU host at load 12-21. With coverage, which the gate always uses, `-n 4` gave no gain (`tests/unit/core`: 126 s
  serial, 131 s parallel). Without coverage it helped (`tests/unit/utils` about 2x, `tests/unit/handlers` 1.31x), but
  the parallel handlers run had two extra failures, both hostile-input scaling timing tests that need a truly serial
  lane. Installing xdist would also make `full_qa_gate` stop refusing a whole-suite run that holds no lock (shown on a
  fixture suite), and break two pytest option-grammar pin tests. No code, config or dependency changed.

## Success Criteria

- [x] A full gate run prints a per-step timing summary, and its report lists the slowest test files and tests.
  Observed on the 2026-10-10 full gate on main (9,654.8 s total, tests 9,266.9 s).
- [ ] A gate interrupted part-way and re-run in resume mode does not repeat the steps that already passed on the same
  tree. **Not yet observed live** (Task 2.2's tests cover it). On 2026-10-10 a commit during the full gate changed
  the tree, so every step's result belonged to the old tree; `all --resume` (3,659.8 s) correctly re-ran them all and
  reused only `smoke_test`, recorded on the new tree. That shows stale results are not reused, not that passing
  ones are. A live check needs a gate interrupted on a tree that then stays still.
- [ ] The full gate's wall-clock time, measured before and after, has dropped. **Not demonstrated.** No single-pass
  "before" total was ever recorded; the closest comparable run (2026-10-09, resumed after a reboot) took 9,779.8 s
  for 129,518 tests, against 9,654.8 s for 135,644 tests today: 1.3% faster in total, about 6% faster per test, inside
  the run-to-run noise (the py3.11 leg alone varied by about 700 s between two earlier runs). The measured savings are
  per hot spot (Task 3.1). [Baseline report](subagent-reports/261010-gate-wall-clock-baseline-sonnet.md). For the
  owner: accept the per-hot-spot savings as the outcome, or ask for a controlled before/after run on a quiet host.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00500-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed.
