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
daemon: a read-only readiness command, a gate refusing `set-mode unattended` on
a coordinator seat until a verified HUMAN GO is on record (Plan 00634), and an
unattended mode that expires at the window end or on the next real human
message.

Sources: usage runway from `session-state --json`; the Plan 00523 answerer's
armed state (00523 Task 2.4); other seats' liveness from `teamchat status` or
fedora-desktop Plan 00251 (`whoami` carries none). The window's authorisations
are ids in the existing `standing_authorisations` list; no second store.

The GO is a questions-room line, so the gate cannot pass until fedora-desktop
issue 369 lets `verify` read that room; until then it denies with that reason.

## Goals

- Readiness command reporting steps 2, 3 and 6 as pass/gap.
- GO gate on arming unattended mode for a coordinator seat.
- Mode expiry (window end or human return); recorded window, queue and
  authorisation ids.
- A verified GO counts as the 00634 cite for its authorised classes until the
  window ends.

## Non-Goals

- Sending the readiness question, authorisation content, a usage ceiling, the
  dialog answerer (Plan 00523). No team means today's behaviour.

## Tasks

### Phase 1: RED

- [ ] ⬜ **Task 1.1**: Fixtures: command output per gap (answerer not armed,
  seat down per `teamchat status`); gate refusal without a verified GO and
  while issue 369 is absent; gate pass with one; a GO covering push lets a push
  through inside the window and not after it, and never covers a not-allowed
  class; expiry at window end and on human return; absent team unchanged.

### Phase 2: Command and mode

- [ ] ⬜ **Task 2.1**: Readiness command.
- [ ] ⬜ **Task 2.2**: Expiring unattended mode and its status display
  (see CLAUDE/SessionModes.md). Targeted QA green.

### Phase 3: GO gate

- [ ] ⬜ **Task 3.1**: Gate using the Plan 00634 check. Advisory first, block
  when the owner rules (Q13). Targeted QA green; live verification.

## Dependencies

- Plan 00631; Plan 00634 (GO verification; fedora-desktop issue 369); Plan
  00523 Task 2.4 (armed state). Related Plans 00470 and 00501.

## Success Criteria

- [ ] Gate cannot be passed by a peer message or an unverified id.
- [ ] Mode lapses on both expiry paths (tests).
- [ ] Absent-team fixture passes.
- [ ] Release-bound items recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed; revised for the fedora-desktop vet.
