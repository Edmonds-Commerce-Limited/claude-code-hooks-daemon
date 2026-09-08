# Plan 00350: ci builds the relay binary so transport gates run

**Status**: Not Started
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Fourteen tests skip in CI with the reason `relay binary not built: <repo>/untracked/bin/hooks-relay` — 11 in
`tests/acceptance/test_transport_toggle_cycle.py` and 3 in
`tests/integration/test_relay_guard_fail_open.py`. The binary is a build
artefact under gitignored `untracked/`, so it is absent from every fresh
checkout and every CI runner, and has been for as long as those tests have
existed.

This is the same defect Plan 00250 fixed for the daemon socket, one artefact
over: a gate that is wired into the workflow, correct, and never load-bearing,
because pytest counts a skip as neither a pass nor a failure. Plan 00250
measured these 14 while counting its own 16 and recorded them as **explicitly
out of scope**, so that a relay gap would not be mistaken for daemon fallout.
This plan is that deferred work.

The relay is the transport that makes a hook dispatch cheap, so the skipped
tests cover a fail-open path with real production consequence: `hooks-relay`
absent or its socket dead must degrade to the Python forwarder rather than
break the hook. Nothing currently proves that on any machine but a developer's
own — and the guard that renders it is described in its own docstring as *"pure
bash builtins only — zero subshells, zero external spawns"*, i.e. a hot path
where a regression is both easy and expensive.

## Goals

- The 14 relay-dependent tests EXECUTE in CI rather than skip, on all three
  interpreters.
- A skip of a relay-dependent gate is visible as a failure rather than absorbed
  into a green run, matching what Plan 00250 established for the daemon gates.
- Building the relay costs the pipeline no more than it has to — the build is
  cached or cheap enough not to be the reason a contributor stops running CI.

## Non-Goals

- Changing the relay's own behaviour, protocol or guard. This plan makes the
  existing tests run; what they assert is already settled.
- Tracking the built binary. It is a compiled artefact and belongs in
  `untracked/`; the fix is to build it, not to commit it.
- Plan 00250's Task 2.4c (the tracked forwarders baking a generating machine's
  absolute path). It touches the same files and is a different question —
  whether `.claude/hooks/*` should be tracked at all.

## Tasks

### Phase 1: Measure

- [ ] ⬜ **Task 1.1**: Confirm the skip count and its distribution against a
  runner condition reproduced locally (a `git worktree`, whose `untracked/` is
  empty — the method Plan 00250 used), rather than against a CI log.
- [ ] ⬜ **Task 1.2**: Establish what building `hooks-relay` costs: toolchain
  required, build time cold and warm, and whether the CI cache already carries
  what it needs.

### Phase 2: Provision

- [ ] ⬜ **Task 2.1**: Build the relay in the CI QA job before `Tests + coverage`, on all three interpreters, without a second job to keep in sync —
  the shape Plan 00250 Task 2.1 settled on for the daemon.
- [ ] ⬜ **Task 2.2**: Fix whatever the 14 tests then report. Assume at least
  one will not have run correctly since it was written; that is what happened
  with the daemon gates.

### Phase 3: Guard the class

- [ ] ⬜ **Task 3.1**: A skip of a relay-dependent gate fails the run. Prefer
  extending the existing declaration-driven guard
  (`tests/acceptance/blocking_gate_guard.py`) over writing a second one — it
  reads its blocking set from `RELEASING.md` Step 12.0, so the cheapest correct
  answer may be to add these files to that declaration.

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Full QA green, daemon restart RUNNING.
- [ ] ⬜ **Task 4.2**: A green CI run in which the 14 tests report as PASSED
  rather than absent.

## Success Criteria

- [ ] The 14 relay-dependent tests report PASSED in CI on all three interpreters
- [ ] A silent skip of a relay-dependent gate fails the run
- [ ] Local `llm_qa.py all` still passes

## Dependencies

- Follows: Plan 00250, which established both the provisioning shape and the
  skip guard this plan should reuse, and which measured these 14 skips while
  deliberately leaving them alone.

## Risks & Mitigations

- **The relay build may need a toolchain CI does not have.** Measure in Task 1.2
  before designing Phase 2; if the cost is real, "provision it" is still the
  precedent (Plan 00245 Decision 3) but the shape of the answer changes.
- **Building on every run may be too slow.** Cache keyed on the relay source, and
  treat a cache miss as a build rather than a skip — a skipped build reproduces
  exactly the defect this plan exists to remove.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00350-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed from Plan 00250's Task 1.1 measurement; dedupe scout checked 41 live
  plans and found no other coverage.
