# Plan 00636: coordinator conduct advisories and board

**Status**: Not Started
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Child (f) of umbrella [Plan 00630](../00630-coordinator-level-skills-ccy-teams-aware/PLAN.md).
It is the umbrella's "B1/B4/B5/B6 child", filed once the coordinator's
self-retrospective arrived, and the home for retrospective situations that had
none (DESIGN.md section 19: s3, s4, s5, s7, s8 wind-down, s11, and the s13
plan-tooling fixes in Phase 3). Every seat item is gated on the 00631 probe (role coordinator, or `any_duty("coordinator")` for
session-level switches) and is absent-safe. v2 `teamchat` only.

## Goals

- B1, B4, B5, B6 guidance and advisories (DESIGN.md section 7).
- s3 directives register: a repeated owner directive is recorded once and
  replayed, never re-asked.
- s4 a Stop check that an owner-facing ask was mirrored to the bus, and
  `AskUserQuestion` denied on coordinator seats (extends
  `R-ASK-USER-QUESTION-UNJUSTIFIED`).
- s4 owner directive (the team chat is the only human surface): a coordinator
  Stop that waits on the owner is refused unless every thread it names got a
  bus post this turn; terminal-only status counts as unsent. Detail, test
  criteria and Q18 (how the handler learns the named threads) in
  [00630 DESIGN.md section 20](../00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md).
- s5 a ci-state reading that tells GitHub "queued" from stuck, and guidance
  never to assert another seat's code without asking it.
- s7 a coordinator board: peers' state in one view, from `teamchat status`
  and fedora-desktop Plan 00251, never from teamchat's files.
- s8 wind-down mode: stops around running background agents stop failing.
- s11 carry-over of coordinator state across compactions.

## Non-Goals

- Wake coalescing itself (delivery belongs to teamchat; a request goes
  upstream). The HUMAN check (00634), the profile and work-queue on dispatch
  (00633), the lane guard (00635). Branch retire (s1, owner decision).

## Tasks

### Phase 1: Scope

- [ ] ⬜ **Task 1.1**: Dedupe each item against the overlaps the scout named
  (it opened 13 of 86 plans, so this is not exhaustive): Plans 00470
  (durable state, s8/s11), 00479 (usage, B6), 00501 (modes, s8 wind-down),
  00632 (liveness, B5); prior art 00117 (`AskUserQuestion` blocker, s4) and
  00601 (session-state contract, s11). Its "merge into 00630" verdict is
  declined: 00630 is the umbrella and planned this child (its Task 1.2).
  Settle Q3 (skill home), Q6 (supervisor action) and Q18 (how the Stop
  handler learns which threads a stop names).
- [ ] ⬜ **Task 1.2**: File the wake-coalescing request with fedora-desktop, and
  the multi-thread bump request (one bus call posts to N threads; open
  teamchat-side dependency of Task 2.1; ask fedora-desktop.1).

### Phase 2: TDD, one item per branch

- [ ] ⬜ **Task 2.1**: s4 (Stop mirror check, `AskUserQuestion` deny, and the
  owner-directive Stop handler). Tests first: a coordinator stop with an
  unposted thread is denied; a worker or unknown role is untouched; a posted
  thread passes; an unreadable bus fails open with a log line. "Posted this
  turn" is read from the read-only teamchat CLI history, no secrets.
- [ ] ⬜ **Task 2.2**: s3 directives register.
- [ ] ⬜ **Task 2.3**: s5 ci-state reading.
- [ ] ⬜ **Task 2.4**: s8 wind-down mode.
- [ ] ⬜ **Task 2.5**: s7 board and B5 liveness.
- [ ] ⬜ **Task 2.6**: s11 carry-over; B1, B4, B6 guidance.

### Phase 3: Plan tooling (retrospective s13)

`CLAUDE/Plan/mkplan.bash` is the template other repositories copy, so these
land here. Not gated on a seat. Each task starts with a failing test.

- [ ] ⬜ **Task 3.1**: `mkplan.bash --journal` accepts the full plan folder name
  as well as the number (red: a slug-named call is refused today).
- [ ] ⬜ **Task 3.2**: The one-line synopsis names the valid journal categories
  and the `--ref` format (red: the synopsis lacks them; 8 of the 9 relayed
  errors were `progress` as a category or a correction without `--ref`).
- [ ] ⬜ **Task 3.3**: `find-plan --body` searches PLAN.md bodies, `Completed/`
  included (red: a body-only term finds nothing today).

## Dependencies

- Plan 00631 (probe). Open, teamchat side: multi-thread bump (Task 1.2).
  Related: 00470, 00501, 00523, 00283; fedora-desktop
  Plan 00251.

## Success Criteria

- [ ] Each item has an absent-team fixture that passes and a coordinator
  fixture that failed first.
- [ ] Release-bound items recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed from the coordinator self-retrospective.
