# Plan 00634: HUMAN-approval check with a cited questions id

**Status**: Not Started
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Child (d) of umbrella [Plan 00630](../00630-coordinator-level-skills-ccy-teams-aware/PLAN.md);
design in its [DESIGN.md](../00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md)
section 16. Before a destructive act (push, delete, permission change, merge to
main) the daemon requires a cited questions-room id and verifies it through the
teamchat CLI history: the sender is a registered human of the team the act
concerns and the line is in the questions room. Transport-agnostic: no
transport internals and no token are read. Failure to verify is a deny with the
reason, never a pass. The same check serves the GO gate of Plan 00632.

## Goals

- Verification module (one teamchat CLI surface) and a short-lived approval
  record.
- PreToolUse guard on the destructive command set, advisory first.

## Non-Goals

- Treating a peer message or a role as approval (invariants 1-3), the
  readiness command, merge approval by agents (Plan 00502).

## Tasks

### Phase 1: RED

- [ ] ⬜ **Task 1.1**: Fixtures: valid human id passes; peer sender, wrong
  room, unknown id, CLI missing, timeout all deny; wrong team's history denies;
  absent team unchanged. Settle Q4 (cite passing) and Q5 (workers).

### Phase 2: Verifier and guard

- [ ] ⬜ **Task 2.1**: Verifier module. Targeted QA green.
- [ ] ⬜ **Task 2.2**: Guard, advisory then block as the owner rules. Targeted
  QA green; live verification.

## Dependencies

- Plan 00631 (team of the act); the teamchat history CLI surface (Plan 00209).
  Consumed by Plan 00632. Related Plan 00502.

## Success Criteria

- [ ] No path counts a peer line or a role as approval (tests).
- [ ] Absent-team fixture passes.
- [ ] Release-bound items recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed.
