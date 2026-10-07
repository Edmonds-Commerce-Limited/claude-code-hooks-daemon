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

- [ ] ⬜ **Task 1.1**: Read-only review of where the time goes and of today's timing data. Report:
  `subagent-reports/261007-qa-speed-review-sonnet.md` (in progress).
- [x] ✅ **Task 1.2** (merge `ae92258cf`): Record each gate step's start, end and duration in its result file, and print a sorted per-step
  timing summary at the end of `llm_qa.py all` (TDD).
- [ ] ⬜ **Task 1.3**: Make the dormant per-test durations real (install pytest-json-report through `uv.lock`, or pass
  `--durations`) and surface the slowest test files and tests in the report.

### Phase 2: Checkpoints and resume

- [ ] ⬜ **Task 2.1**: Confirm the existing provenance (`llm_qa.py:371-520`) is enough to key a checkpoint: every step,
  including each matrix leg, records the tree it ran on, so a stale result can never be taken as a pass.
- [ ] ⬜ **Task 2.2**: A resume mode that skips steps whose passing result matches the current tree and runs the rest.
- [ ] ⬜ **Task 2.3**: Give each matrix leg and scope (`unit`, `rest`) its own checkpoint, so a reboot mid-tests loses
  only the leg it interrupted, while coverage is still judged on the whole (parallel coverage mode is disabled today,
  `pyproject.toml:135-136`).

### Phase 3: Speed

- [ ] ⬜ **Task 3.1**: Act on the measured hot spots: the slowest tests, steps that can run concurrently, any
  duplicated work such as repeated matrix legs.
- [ ] ⬜ **Task 3.2**: Evaluate pytest-xdist (running tests across cores): whether the suite is safe in parallel
  (sockets, ports, working directory, the full-QA lock and its sink plugin), and adopt it if it is.

## Success Criteria

- [ ] A full gate run prints a per-step timing summary, and its report lists the slowest test files and tests.
- [ ] A gate interrupted part-way and re-run in resume mode does not repeat the steps that already passed on the same
  tree.
- [ ] The full gate's wall-clock time, measured before and after, has dropped.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00500-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed.
