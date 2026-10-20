# Plan 00538: supervisor auto refocus and focus signal

**Status**: Not Started
**Created**: 2026-10-20
**Owner**: dev
**Priority**: Low
**GitHub Issue**: #125 (follow-up, split out by the Fable stand-in ruling in [Plan 00537](../Completed/00537-supervisor-holds-sends-off-main-focus/RULING-fable.md))
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00537 makes the ccy supervisor hold every send while the human's own keys
show focus may have left the main prompt. The hold ends only on a bare Esc from
the human. That is safe, but it has two costs:

- **A false hold.** A history-recall Up in a session with no sub-agent panel
  holds until the human presses Esc.
- **A hold that waits on the human.** Nothing clears it in an unattended session.

This plan holds what was split out of #125.

## Goals

- **Phase 1, engineering (a spike).** Find out whether Claude Code exposes the
  selected or viewed thread anywhere other than the screen, on the installed
  version:

  - the `subagentStatusLine` input;
  - a hook payload field;
  - a state file.

  Any such signal would be a second, positive way to clear Plan 00537's latch.
  Plan 00158 found the main status-line payload carries no focus field, so look
  past it.

- **Phase 2, owner decision: auto-refocus.** The supervisor would press keys
  to return focus to the main thread, read off a host-side screen model. Today
  it only reacts to the human's keys. This decision is the owner's, for three
  reasons:

  - it is a new keystroke into a session the supervisor cannot see;
  - the right key differs by state (Esc for a selected row, unknown for an open
    transcript, and Up may recall history);
  - [Plan 00160](../00160-supervisor-foreground-identity-and-reaping/PLAN.md)
    already judged screen-scraping fragile.

  [Plan 00453](../00453-supervisor-modal-overlay/PLAN.md) (supervisor modal
  overlay) is the related screen-side work.

- **Phase 2, owner decision: the mods `$.prompt.submit` route.** It contradicts
  [Plan 00497](../00497-hooks-daemon-mod/PLAN.md)'s standing
  ruling that the ccy supervisor stays outside mods.

## Non-Goals

- Changing Plan 00537's hold or its fail direction.

## Tasks

### Phase 1: Spike

- [ ] ⬜ **Task 1.1**: On the installed Claude Code version, capture
  `subagentStatusLine` input and hook payloads while a sub-agent row is
  selected, and while its transcript is open. Record whether any field names
  the viewed thread.
- [ ] ⬜ **Task 1.2**: If one does, red test, then use it as a second way to
  clear the latch. It may clear the hold only on positive evidence that the main
  thread has focus.

### Phase 2: Owner questions (agent-needs-human)

- [ ] ⬜ **Task 2.1**: Put auto-refocus and the mods route to the owner, with
  the Phase 1 result.

## Notes

- **For #127**, which shares the restart `/exit` path: a restart request is
  persisted only when `/exit` was actually sent, never on a hold. That is Plan
  00537's rule.

## Success Criteria

- [ ] The Phase 1 finding is recorded, and any shipped clearing signal has a
  test that failed before it.
- [ ] Any shipped change has a release note in the pending-release holding area
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- <!-- delivery commit hashes -->
