# Plan 00321: injected goal has no retraction path

**Status**: Not Started
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Agent

## Overview

The supervisor can SET Claude Code's session `/goal` slot but can never clear
it. `load_goal_signal` reads a `<session>.goal-intent` file and injects
`/goal <line>`; `hooks-daemon inject-goal NNNNN` does the same on demand and
requires an ACTIVE plan number. Nothing in the supervisor, the daemon CLI, or
the handler set emits a clearing `/goal`. The slot holds one condition on
last-writer-wins, so once a condition is in it, the only ways out are a human
typing `/goal`, another plan flipping to In Progress and displacing it, or the
session ending.

That makes a stale condition unclearable from inside the session, and the Stop
challenge keeps evaluating against it every turn. Plan 00320 fixed the two
defects that let a stale goal be CREATED — the sidecar was not retracted when
the ledger emptied, and a plan-shaped path anywhere on disk could emit a goal
naming a project path that does not exist. Neither helps a condition already
sitting in the slot: those fixes stop the next one, and this plan is about the
current one.

Observed at the end of the v3.60.0 release session. The `/goal` slot holds
`Work on Plan 00099 (Plan 00099) at CLAUDE/Plan/00099-test` — a folder that has
never existed (the real 00099 is `00099-python-fingerprint-venv-isolation`,
archived Complete). The daemon-side goal ledger holds zero live entries and no
`.goal-intent` sidecar remains, so every daemon-side source agrees no goal is
owed; only the upstream slot disagrees, and it is the one the Stop challenge
reads. The condition is unsatisfiable by construction: no work can complete a
plan whose folder is absent, so the session can only stop by arguing with the
challenge rather than by discharging it.

## Goals

- When the goal ledger goes from some live entries to zero, the supervisor
  RETRACTS the session goal rather than leaving the last condition standing.
- A stale or unsatisfiable condition can be cleared without ending the session
  and without a human typing `/goal`.
- The daemon's three goal surfaces (ledger, sidecar, upstream `/goal` slot)
  cannot disagree about whether a goal is owed. Two of the three already agree
  after Plan 00320; this closes the third.

## Non-Goals

- Re-opening Plan 00320. Its two fixes are correct and live-verified; they
  govern goal CREATION, and this plan governs goal RETRACTION.
- Teaching the Stop handler to ignore a condition whose plan folder is missing.
  That hides an unsatisfiable goal instead of retracting it, and a stale goal
  naming a plan that DOES exist would still slip through.

## Open Question (blocks Task 1.2 — needs a human or upstream answer)

**Does Claude Code's `/goal` accept a clearing form?** A bare `/goal`, an empty
argument, or an explicit `/goal none` may or may not clear the slot; this was
not verified, and guessing wrong would inject a literal junk condition instead
of clearing it — strictly worse than the stale one. Establish the real
semantics before implementing, from upstream documentation or a deliberate
manual test in a scratch session, NOT by trying it in a live one.

## Tasks

### Phase 1: Establish and implement retraction

- [ ] ⬜ **Task 1.1**: Answer the Open Question above and record the verified
  `/goal` clearing semantics in this plan.
- [ ] ⬜ **Task 1.2**: Teach the supervisor to inject the clearing form when a
  retirement takes the ledger to zero live entries — the same trigger that now
  retracts the sidecar, extended to the upstream slot. Gate it so it fires only
  on the some-to-zero transition, never on a session that never had a goal.
- [ ] ⬜ **Task 1.3**: Add a `hooks-daemon clear-goal` counterpart to
  `inject-goal`, so a stale condition can be cleared on demand without waiting
  for a retirement. `inject-goal` deliberately requires an ACTIVE plan number,
  so it cannot be reused for this.
- [ ] ⬜ **Task 1.4**: Regression tests pinning the some-to-zero transition, and
  pinning that a still-live plan keeps its condition — the same boundary Plan
  00320 pinned for the sidecar.

## Success Criteria

- [ ] A retirement that empties the ledger leaves no condition in the `/goal`
  slot, verified live by a Stop that is not challenged.
- [ ] The three goal surfaces agree in every state, with a test per surface.
- [ ] `./scripts/qa/llm_qa.py all` passes 25/25.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00321-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
