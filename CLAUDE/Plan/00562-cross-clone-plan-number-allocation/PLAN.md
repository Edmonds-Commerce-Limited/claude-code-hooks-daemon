# Plan 00562: cross clone plan number allocation

**Status**: In Progress
**Created**: 2026-11-04
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #154

## Overview

`CLAUDE/Plan/mkplan.bash` and the daemon's plan-number helper (`handlers/utils/plan_numbering.py`, built by Plan 00112 and reused by Plan 00144) give out the next plan number as the higher of two sources: the per-clone git counter `hooksdaemon.latestPlanNumber`, and the highest plan folder on disk in the current checkout. Both sources are local. A plan claimed in another clone, or on a branch not yet merged, is invisible to them, so two clones of one repository can take the same number, and the clash only shows when their branches meet. This was observed in the field and reported on #152, and Plan 00558 deferred it to a separate plan.

Inside one clone, including its linked worktrees, concurrent runs are already serialised by the scaffold lock in the common git directory (Plan 00474, #59). This plan covers the cross-clone case, which no local lock can reach.

The fix needs a source every clone shares. Because `mkplan.bash` ships to every client project, the choice was the owner's: option (a), a read-only remote scan (Q1 below).

## Goals

- Two clones of one repository never take the same plan number when both can reach the shared remote.
- With no remote reachable, allocation still succeeds with today's local answer and says that it could not check.
- The common single-clone case does not slow down noticeably.

## Non-Goals

- The same-clone race. Plan 00474's lock already covers it.
- Renumbering plans that already collided.

## Owner questions

- **Q1: which shared source? Answered 4 November 2026: (a), the read-only remote scan.** Nothing is pushed. A reservation ref is not built.
  - **(a) Read-only remote scan:** fetch, then take the highest plan number on the remote default branch and every remote branch. It pushes nothing, but every scaffold pays for a fetch, and two clones that have not pushed yet can still collide.
  - **(b) Reservation ref:** push `refs/plan-reservations/NNNNN` when scaffolding, so a second clone's push of the same number is rejected and it retries with the next one. This is a real guarantee, but it writes a new ref namespace to every client's remote and needs push access when scaffolding.
  - **(c) Both:** scan first, then reserve.
  - **Recommendation:** (a) as the default, with (b) as an opt-in config option. A read-only default changes nothing in the client's remote, and it closes the observed case, where the first clone had pushed its plan hours earlier.
- **Q2:** with (a), how long may the fetch run before allocation falls back to the local answer? The owner did not answer this separately, so the recommended default stands: the existing `Timeout.GIT_FETCH_SESSION`.

## Tasks

### Phase 1: decision

- [x] ✅ **Task 1.1**: Owner answers Q1 (a). Q2 takes the recommended default.

### Phase 2: implementation

- [ ] ⬜ **Task 2.1**: Write a failing test that reproduces the cross-clone collision: two clones of a bare remote, one scaffolds and pushes, the other scaffolds the same number.
- [ ] ⬜ **Task 2.2**: Implement the chosen source in `mkplan.bash` and in `plan_numbering.py` together, so the two cannot disagree.
- [ ] ⬜ **Task 2.3**: Test the offline fallback and the "could not check" message.

## Success Criteria

- [ ] The collision test from Task 2.1 passes.
- [ ] The offline test passes.
- [ ] A release note in the pending-release holding area (`CLAUDE/UPGRADES/UNRELEASED/`) describes the changed allocation, because `mkplan.bash` is deployed to clients.
- [ ] GitHub #154 is commented on and closed.

## Delivery & Milestones

- Triage: GitHub #154 (parked `agent-needs-human` pending Q1).
