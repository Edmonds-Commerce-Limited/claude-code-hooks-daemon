# Plan 00635: host-seat lane guard

**Status**: In Progress
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

## Decision (owner, lts-infra Q64 D3, settled; 00630 Q14)

Build the handler. On a seat whose duty (per team, from `teamchat whoami --json`) is host, the guard refuses test, build, lint and QA commands. The
static deny rule is fedora-desktop's `cc-deny.json` (the coordinator is having
fedora-desktop.1 add the host-seat entries); this plan adds no deny-rule task.
An unreadable `whoami` means role unknown and the guards stay armed.

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

- [x] ✅ **Task 1.1**: Record the Q64 ruling in the umbrella DESIGN.md
  (Q14 and section 15, settled).
- [ ] ⬜ **Task 1.2** (test-first, red before the handler): duty `host` in any
  held team denies pytest, npm test, build, lint and QA commands incl. `sh -c`
  and scripts; deploy and triage allowed; worker and coordinator unaffected;
  unreadable `whoami` = role unknown, guards armed; absent team unchanged;
  probe with no answer reports once (Q9).

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
