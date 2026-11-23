# Plan 00633: coordinator profile and peer-branch gate recipe

**Status**: Not Started
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Child (c) of umbrella [Plan 00630](../00630-coordinator-level-skills-ccy-teams-aware/PLAN.md);
design in its [DESIGN.md](../00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md)
section 14 (features 3 and 4). Two parts. (1) A coordinator profile: one
setting that turns on the goal ledger, crons, park-and-move-on for
awaiting-human when unattended, work-queue enforcement on dispatch and the
`standing_authorisations` handler (the one authorisation store). It sets
existing per-feature keys and owns no new mechanism. (2) The peer-branch gate
recipe (B12, which is also B3): a declared `gate_command` that
`merge_qa_advisor` and the work-queue record per merged branch (`--no-ff`
merge, Layer 1 and 2 QA, push only if green, else `reset --keep`, one at a
time).

The profile's switches are session-level and concern no team, so it applies
while the seat is coordinator in ANY held team (`any_duty("coordinator")`).
There is no repo-to-team map. A gated act that names a team (a push cite)
still gates on that team, through Plan 00634.

## Goals

- `role_profile` key enabling the listed switches, honouring explicit per-key
  overrides (Q15).
- `gate_command` declared once; each merged branch gets a recorded gate result.

## Non-Goals

- New work-queue storage (Plan 00470 Task 3.3), a second authorisation store,
  merge approval (Plan 00502), the HUMAN check (Plan 00634).

## Tasks

### Phase 1: RED

- [ ] ⬜ **Task 1.1**: Fixtures: profile on for a coordinator-in-A,
  worker-in-B session; off for a worker-only, probe-only or host-duty session;
  override wins; unknown role unchanged; record written per merge; no record on
  a failed gate.

### Phase 2: Profile

- [ ] ⬜ **Task 2.1**: Profile resolver over existing keys. Targeted QA green.

### Phase 3: Gate recipe

- [ ] ⬜ **Task 3.1**: `gate_command` config and per-branch record in
  `merge_qa_advisor` / work-queue. Targeted QA green; live check.

### Phase 4: Upgrade preset (owner ruling Q66 (b))

Design: [00630 DESIGN.md section 22](../00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md).
Not seat-gated: a default in every project.

- [ ] ⬜ **Task 4.1**: Tests first: the four `upgrade.automatic_scope` values
  (major, minor, patch, none) against a fixed current version and tag list;
  one-line notice at a forbidden boundary, never a block; manual upgrade
  unaffected; unparseable tags select nothing.
- [ ] ⬜ **Task 4.2**: `upgrade` built-in preset in `standing_authorisations`,
  shipped enabled, recorded-request wording naming the key, default `major`
  (put to the owner in Q66: attended `major` now, unattended waiting on
  00625 signed tags; DESIGN.md section 22). Does not authorise an unattended
  upgrade; that waits on Plan 00625's signed-tag verification.

## Dependencies

- Plan 00631. Related Plans 00470 (work-queue), 00502 (merge gate).

## Success Criteria

- [ ] Every merged branch has a gate record or an explicit "not gated".
- [ ] Absent-team fixture passes; profile never relaxes a guard.
- [ ] Release-bound items recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed; revised for the fedora-desktop vet.
