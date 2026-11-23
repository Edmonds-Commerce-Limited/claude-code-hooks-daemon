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
desktop level, and they are not workers. Recommended design: a PreToolUse
handler refusing QA, test and build commands in a host seat, reusing the
existing command classification, with Claude Code deny rules only as a cheap
second layer (they miss scripts and `sh -c`).

## DECISION PENDING (owner, lts-infra Q64)

Build the handler (recommended), or deny rules alone? Execution of Phase 2
waits for the ruling. If deny rules alone, this plan reduces to documenting the
rule set. Keyed on seat kind `host` and, if it lands, the `deployer` role
(Plan 00207); roles come from teamchat per team, so the guard fires for acts
concerning a team where the seat is host.

## Goals

- A host-seat QA/test/build command is refused with a message naming the lane;
  deployment and triage commands are untouched; advisory first.

## Non-Goals

- Blocking container seats, any non-host seat, or an unknown seat kind.

## Tasks

### Phase 1: Decision and RED

- [ ] ⬜ **Task 1.1**: Record the Q64 ruling in the umbrella DESIGN.md.
- [ ] ⬜ **Task 1.2**: RED fixtures: host denied for test/QA/build incl. `sh -c`
  and scripts; deploy and triage allowed; container, unknown and absent seats
  unchanged.

### Phase 2: Handler

- [ ] ⬜ **Task 2.1**: Handler reusing command classification, advisory first.
  Targeted QA green.
- [ ] ⬜ **Task 2.2**: Optional deny-rule second layer; live verification in a
  host seat; promote to block when ruled.

## Dependencies

- Plan 00631 (seat kind per team); the Q64 ruling. Related fedora-desktop
  Plans 00263 and 00207.

## Success Criteria

- [ ] Fixtures above pass; absent-team fixture passes.
- [ ] Release-bound items recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed.
