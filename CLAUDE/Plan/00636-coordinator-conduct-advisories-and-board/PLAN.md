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
- s4 MUST (owner HARD requirement): a waiting-on-human stop is countered by a
  deterministic recent-notifying-bump check on every open question the seat
  owns; the stop text points at threads, never restates the waits (Task 2.1a).
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
  (unverified here: no scout report for 00636 exists; the only scout report
  on disk is `CLAUDE/Plan/00630-*/subagent-reports/hooks-daemon-plan-dedupe-scout-haiku.md`,
  which says "Checked 79 live plans" and "proceed. Nothing to merge or
  supersede", so this list is the author's own, not exhaustive; re-dispatch
  the scout for 00636 before filing): Plans 00470
  (durable state, s8/s11), 00479 (usage, B6), 00501 (modes, s8 wind-down),
  00632 (liveness, B5; weak owner, it covers the unattended readiness gate);
  prior art 00117 (`AskUserQuestion` blocker, s4) and
  00601 (session-state contract, s11). 00630 is the umbrella and planned this
  child (its Task 1.2).
  Settle Q3 (skill home), Q6 (supervisor action), the default N minutes for
  the recent-bump window, and Q18's second half. Q18's first half is settled
  by DESIGN.md 20.1: every open question the seat asked or owns, no parsing
  of the stop reason.
- [ ] ⬜ **Task 1.2**: File the wake-coalescing request with fedora-desktop.
  The multi-thread bump is already requested: fedora-desktop request 00209
  R11 (`teamchat bump <ids> [--note ...]`, `teamchat bump --waiting`,
  notifying by default; unverified here: relayed bus text only, no teamchat
  binary or clone in this checkout); track it landing in teamchat, the dependency of
  Task 2.1. Ask fedora-desktop.1 whether history marks a bump post (and any
  post) as notifying, which settles Q18's second half. Open item: `pingbus history --help` documents only `--team`, `--limit` and `--room`, no notify
  field, so v1 is not shown to supply the flag; the fail-closed rule applies
  until confirmed (DESIGN.md 20.1).

### Phase 2: TDD, one item per branch

- [ ] ⬜ **Task 2.1**: s4 (Stop mirror check, `AskUserQuestion` deny, and the
  owner-directive Stop handler). Tests first: a coordinator stop with an
  unposted thread is denied; a worker or unknown role is untouched; a posted
  thread passes; an unreadable bus fails open with a log line. "Posted this
  turn" is read from the read-only teamchat CLI history, no secrets. Only a
  NOTIFYING post counts: a plain post to the named thread leaves the stop
  denied (the owner missed bumps that landed silently), and a post whose
  notify status cannot be read counts as non-notifying (fail closed). The
  remedy is ONE call: a refused stop prints the exact
  `teamchat bump <ids>` command naming every unposted thread (R11). Depends
  on R11 landing in teamchat.
- [ ] ⬜ **Task 2.1a** (MUST, owner HARD requirement, test-first; extends
  2.1 and supersedes its "posted this turn" rule): the waiting-on-human Stop
  check of DESIGN.md 20.1. Red tests first: detect a waiting stop by reason
  text or awaiting-human mode; for every open question the seat asked or
  owns require a NOTIFYING post within N minutes (configurable) with a
  non-boilerplate body; otherwise deny and print the one bump command for the
  stale threads; deny text names ids only and never restates the waits;
  unreadable notify flag counts as non-notifying; worker and unknown role
  untouched; unreadable bus fails open with a loud log. Deterministic: ids,
  timestamps, notify flag; no LLM judgement. Acceptance tests are the
  20.1 list.
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
  errors were (unverified here: the relayed retrospective is not on disk) `progress` as a category or a correction without `--ref`).
- [ ] ⬜ **Task 3.3**: `find-plan --body` searches PLAN.md bodies, `Completed/`
  included (red: a body-only term finds nothing today).

## Dependencies

- Plan 00631 (probe). Teamchat side: fedora-desktop request 00209 R11
  (`teamchat bump`) landing in teamchat (Task 2.1).
  Related: 00470, 00501, 00523, 00283; fedora-desktop
  Plan 00251.

## Success Criteria

- [ ] Each item has an absent-team fixture that passes and a coordinator
  fixture that failed first.
- [ ] Release-bound items recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed from the coordinator self-retrospective.
