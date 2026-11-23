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
section 14 (features 3 and 4). Two parts. (1) A coordinator role profile: one
setting that turns on the goal ledger, crons, park-and-move-on for
awaiting-human when unattended, work-queue enforcement on dispatch and the
owner's standing authorisations. It sets existing per-feature keys and owns no
new mechanism. (2) A peer-branch gate recipe: a declared `gate_command` that
`merge_qa_advisor` and the work-queue record per merged branch, so "merged and
gated" is a record, not a habit (`--no-ff` merge, Layer 1 and 2 QA, push only if
green, else `reset --keep`, one at a time).

The profile applies per team: it is active for acts concerning a team where
the seat is coordinator, never session-wide.

## Goals

- `role_profile` key enabling the listed switches, honouring explicit per-key
  overrides (Q15).
- `gate_command` declared once; each merged branch gets a recorded gate result.

## Non-Goals

- New work-queue storage (Plan 00470 Task 3.3), merge approval (Plan 00502),
  the HUMAN check (Plan 00634).

## Tasks

### Phase 1: RED

- [ ] ⬜ **Task 1.1**: Fixtures: profile off for a worker-in-B/coordinator-in-A
  session on B's acts; override wins; unknown role unchanged; record written per
  merge; no record on a failed gate.

### Phase 2: Profile

- [ ] ⬜ **Task 2.1**: Profile resolver over existing keys. Targeted QA green.

### Phase 3: Gate recipe

- [ ] ⬜ **Task 3.1**: `gate_command` config and per-branch record in
  `merge_qa_advisor` / work-queue. Targeted QA green; live check.

## Dependencies

- Plan 00631. Related Plans 00470 (work-queue), 00502 (merge gate).

## Success Criteria

- [ ] Every merged branch has a gate record or an explicit "not gated".
- [ ] Absent-team fixture passes; profile never relaxes a guard.
- [ ] Release-bound items recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed.
