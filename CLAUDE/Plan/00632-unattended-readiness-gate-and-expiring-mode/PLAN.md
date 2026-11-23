# Plan 00632: unattended readiness, GO gate, expiring mode

**Status**: Not Started
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Child (b) of umbrella [Plan 00630](../00630-coordinator-level-skills-ccy-teams-aware/PLAN.md);
spec in its [DESIGN.md](../00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md)
section 13 (the lts-infra eight-step readiness protocol). Mechanism in the
daemon: a read-only readiness command (usage runway, crons, seat liveness), a
gate refusing `set-mode unattended` on a coordinator seat until a verified
HUMAN GO is on record, and an unattended mode that expires at the window end or
on the next real human message. Project authorisations stay in project docs;
the readiness question type belongs to teamchat.

The owner ruled NO usage ceiling (10:28Z): the supervisor answers the
rate-limit dialog (Plan 00523, referenced, not recreated). Readiness step 2
only checks that it is armed.

## Goals

- `hooks-daemon` readiness command reporting steps 2, 3 and 6 as pass/gap.
- GO gate on arming unattended mode for a coordinator in the concerned team.
- Mode expiry (window end or human return); recorded window, queue and
  authorisations.

## Non-Goals

- Sending the readiness question (transport), authorisation content, the usage
  ceiling, the dialog answerer (Plan 00523). No team means today's behaviour.

## Tasks

### Phase 1: RED

- [ ] ⬜ **Task 1.1**: Fixtures: command output per gap, gate refusal without a
  verified GO, gate pass with one, expiry at window end and on human return,
  absent-team unchanged.

### Phase 2: Command and mode

- [ ] ⬜ **Task 2.1**: Readiness command.
- [ ] ⬜ **Task 2.2**: Expiring unattended mode and its status display
  (see CLAUDE/SessionModes.md). Targeted QA green.

### Phase 3: GO gate

- [ ] ⬜ **Task 3.1**: Gate using the Plan 00634 check. Advisory first, block
  when the owner rules (Q13). Targeted QA green; live verification.

## Dependencies

- Plan 00631 (role in the concerned team); Plan 00634 (GO verification);
  Plan 00523 (answerer, step 2). Related Plans 00470 (persistent sessions,
  work-queue) and 00501 (session modes); fold shared pieces rather than
  duplicate (dedupe scout).

## Success Criteria

- [ ] Gate cannot be passed by a peer message or an unverified id.
- [ ] Mode lapses on both expiry paths (tests).
- [ ] Absent-team fixture passes.
- [ ] Release-bound items recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed.
