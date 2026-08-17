# Plan 00250: CI must actually run the acceptance gates it calls blocking

**Status**: Not Started
**Created**: 2026-08-17
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The first fully green CI run (`4d1a553b1`, run 32033242091) was also the first
run whose skips were named, because Plan 00245 had just added `-rs` to the CI
pytest step. It named 11 skipped tests nobody knew were skipping:

| File                                                 | Skips | Reason given                                                 |
| ---------------------------------------------------- | ----- | ------------------------------------------------------------ |
| `tests/acceptance/test_absolute_path_socket_deny.py` | 6     | "Daemon not running — no live socket found under untracked/" |
| `tests/acceptance/test_stop_hook_hard_block.py`      | 3     | "Daemon not running"                                         |
| `tests/acceptance/test_tool_use_error_recovery.py`   | 2     | "Daemon not running — no live socket found under untracked/" |

All three files need a live daemon socket and skip cleanly without one. CI never
starts a daemon in the QA job, so all 11 have skipped on every run since they
were written.

`CLAUDE/development/RELEASING.md` Step 12.0 names all three files as BLOCKING
acceptance gates, and about one of them says explicitly:

> The test skips cleanly when no daemon is running locally; under H-1 the daemon
> is always started before this step, **so a skip there is itself an abort
> condition.**

CI does not know that. It reports the run green.

## This is a blind guard, not a missing feature

The tests exist, they are correct, and they are wired into the workflow. What is
missing is any mechanism by which their absence is noticed — the exact shape of
`CLAUDE.md` Core Standard 15 (DBF), and the second instance of it inside Plan
00245 alone. That plan's Decision 3 already settled the general question for the
`uv` case: **prefer providing the dependency in CI to skipping**. This applies
the same decision to the daemon.

The `Daemon load` job in the same workflow starts a daemon successfully on the
runner, so this is a provisioning gap rather than a platform limitation.

## Goals

- The three socket-dependent acceptance files EXECUTE in CI rather than skip.
- A skip of a gate that `RELEASING.md` declares blocking fails the run, so this
  class cannot go unnoticed again — for these three files or the next one.
- The declaration lives in ONE place, so a file added to the blocking set in
  `RELEASING.md` does not silently stay unguarded.

## Non-Goals

- Making every acceptance test run in CI. Some are genuinely
  `harness_cannot_produce` (Plan 00196 documented `test_absolute_path_socket_deny`
  that way for the *playbook*; that is about rendering, not about whether the
  pytest file can run against a socket).
- Reworking the acceptance playbook harness — that is Plan 00243's scope, and it
  refines skip RENDERING rather than skip VISIBILITY.
- Changing what the tests assert.

## Context & Background

Confirmed by the dedupe scout across all 36 live plans: no live plan covers
this. Plan 00245 (skip visibility via `-rs`, and `if: !cancelled()` so one
failing step stops hiding later ones) and Plan 00243 (playbook skip-rendering)
are both strict subsets — neither starts a daemon in CI, and neither makes a
silent skip of a declared-blocking gate fail anything.

Plan 00245 is what FOUND this, and deliberately did not absorb it: that plan's
goal was a green CI, and it is met. Widening it to also provision a daemon would
have reopened a plan whose success criteria were satisfied.

## Tasks

### Phase 1: Establish the gap as a test, not a claim

- [ ] ⬜ **Task 1.1**: Pin the current behaviour — a run with no daemon skips
  exactly these 11 tests, and nothing reports it
  - [ ] ⬜ Reproduce locally with the daemon stopped, so the count and the skip
    reasons are observed rather than read off a CI log
- [ ] ⬜ **Task 1.2**: Establish where the blocking set is declared, and whether
  `RELEASING.md` Step 12.0's list can be read mechanically or must be restated
  - [ ] ⬜ If it must be restated, that duplication is itself the defect to fix
    first — a second copy is the one that goes stale

### Phase 2: Make the gates run

- [ ] ⬜ **Task 2.1**: Start a daemon in the CI QA job before the acceptance
  step, reusing whatever the `Daemon load` job already does rather than inventing
  a second way to start one
- [ ] ⬜ **Task 2.2**: Confirm all 11 tests EXECUTE on all three interpreters
  - [ ] ⬜ Expect first-run failures and treat them as long-standing, not as
    regressions — the LESSONS.md entry on waking skipped tests applies directly
- [ ] ⬜ **Task 2.3**: Verify the CI daemon cannot collide with anything (its own
  `HOSTNAME`-derived socket, per the hostname-isolation design)

### Phase 3: Guard the class

- [ ] ⬜ **Task 3.1**: A skip of a declared-blocking acceptance gate fails the
  run, naming the file and that it is declared blocking
- [ ] ⬜ **Task 3.2**: A test that fails when a file is added to the blocking set
  without being covered, so the guard cannot drift from the declaration

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Full QA green, daemon restart RUNNING
- [ ] ⬜ **Task 4.2**: A green CI run in which the 11 tests are reported as
  PASSED rather than absent

## Dependencies

- Follows: Plan 00245 (the `-rs` change that surfaced this; its Decision 3 is the
  precedent for provisioning over skipping).
- Related: Plan 00243, which handles skip rendering in the playbook rather than
  skip visibility in CI.
- Related: Plan 00244, whose project-handler CI step had the same "wired in but
  not load-bearing" property until CI went green.

## Technical Decisions

### Decision 1: provision the daemon rather than relax the tests

**Context**: the cheap fix is to leave the skips alone — they are honest, and the
tests do pass locally under H-1 during a release.

**Decision**: provision. A gate that only ever runs during a manual release step
is not a gate against the commits that reach `main` between releases, which is
precisely when a regression is cheapest to catch. Plan 00245's Decision 3 already
chose this for `uv`, and the argument is identical.

**Date**: 2026-08-17

## Success Criteria

- [ ] The 11 tests report PASSED in CI on all three interpreters, not skipped
- [ ] A silent skip of a declared-blocking gate fails the run
- [ ] The blocking set has one source of truth
- [ ] Local `llm_qa.py all` still passes

## Risks & Mitigations

| Risk                                                        | Impact | Probability | Mitigation                                                                                     |
| ----------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------- |
| The 11 tests fail on a runner for reasons unrelated to this | Medium | High        | Expected — Plan 00245's Phase 3 was exactly this work; treat as long-standing, fix root causes |
| A CI daemon interferes with another job                     | Medium | Low         | Hostname-based isolation already gives each environment its own socket/PID path                |
| Guarding the blocking set duplicates `RELEASING.md`         | Medium | Medium      | Task 1.2 settles the single source of truth BEFORE the guard is written                        |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed at the commit that adds this plan.
