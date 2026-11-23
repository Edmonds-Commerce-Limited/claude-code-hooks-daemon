# Plan 00635: host-seat lane guard

**Status**: Not Started
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Child (e) of umbrella [Plan 00630](../00630-coordinator-level-skills-ccy-teams-aware/PLAN.md);
design in its [DESIGN.md](../00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md)
section 15 (fedora-desktop Plan 00263 D3). Owner ruling (lts-infra Q62): host
sessions should not run tests; host seats are for deployments or triage at
desktop level, and they are not workers.

This plan owns ONE layer: the dynamic, by-duty check. A PreToolUse handler
refuses QA, test and build commands when any held team of the session has duty
`host` (from `teamchat whoami --json`), reusing the existing command
classification. The static layer is fedora-desktop's: `cc-run` writes
`cc-deny.json` from the seat's duty and passes it on a host launch. This plan
builds no deny rules.

## DECISION PENDING (owner, lts-infra Q64)

Build the handler (recommended by fedora-desktop Plan 00263 and here)? Phase 2
waits for the ruling. If the owner chooses the static layer alone, this plan is
cancelled.

## Goals

- In a session holding a team with duty `host`, a QA/test/build command
  (including via `sh -c` and scripts) is refused with a message naming the
  lane; deployment and triage commands are untouched; advisory first.

## Non-Goals

- Deny rules (fedora-desktop's `cc-deny.json`). A host `cc` session with no
  team (it has no duty; fedora-desktop's static layer covers it). Any session
  with no `host` duty.

## Tasks

### Phase 1: Decision and RED

- [ ] ⬜ **Task 1.1**: Record the Q64 ruling in the umbrella DESIGN.md.
- [ ] ⬜ **Task 1.2**: RED fixtures: duty `host` in any held team denies
  test/QA/build incl. `sh -c` and scripts; deploy and triage allowed; worker,
  coordinator, unknown duty and absent team unchanged; probe with no answer
  reports once (Q9).

### Phase 2: Handler

- [ ] ⬜ **Task 2.1**: Handler reusing command classification, advisory first;
  live verification in a host-duty seat; promote to block when ruled.
  Targeted QA green.

## Dependencies

- Plan 00631 (`any_duty`); the Q64 ruling. Related fedora-desktop Plan 00263
  (static layer).

## Success Criteria

- [ ] Fixtures above pass; absent-team fixture passes.
- [ ] Release-bound items recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed; revised for the fedora-desktop vet (duty, layer ownership).
