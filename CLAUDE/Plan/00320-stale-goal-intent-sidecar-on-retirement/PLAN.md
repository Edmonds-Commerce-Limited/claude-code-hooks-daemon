# Plan 00320: stale goal intent sidecar on retirement

**Status**: In Progress
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Agent

## Overview

When the last live plan in the goal ledger retires, the daemon leaves the
session's `<session>.goal-intent` sidecar file on disk still asserting that
retired goal. The ledger and the sidecar then disagree permanently: the ledger
holds zero live entries, while the sidecar — the file the supervisor's Stop
challenge actually reads — keeps naming a plan nobody is working on.

The defect is in `goal_injection.py`. On a terminal-status write,
`_maybe_refresh_on_retirement` re-renders the combined signal with
`fallback=None`. If the ledger now has no live refs, `_write_combined_signal`
falls through to `_write_fallback`, which returns `None` for a `None` fallback
and writes nothing. The docstring states the intent correctly — "write nothing
in that case rather than re-asserting a goal for a plan that just went
terminal" — but writing nothing is not the same as retracting: the sidecar
written moments earlier survives untouched. `write_goal_signal` has no removal
counterpart, so nothing in the module can ever clear a sidecar.

Observed live during the v3.60.0 release. An acceptance-test fixture flipped
plan `00099` to In Progress at `12:00:50.361`; the ledger retired it
`terminal-status` three seconds later at `12:00:50.367`+3s. Twenty-nine minutes
later, after the release had been tagged, published and verified, the Stop
handler challenged the session's stop with
`Work on Plan 00099 (Plan 00099) at CLAUDE/Plan/00099-test` — a path that has
never existed (the real 00099 is `00099-python-fingerprint-venv-isolation`,
archived Complete). The goal was unsatisfiable by construction: no amount of
work can complete a plan whose folder is absent, so the session could only stop
by arguing with the challenge rather than by satisfying it.

## Goals

- A retirement that empties the ledger REMOVES the session's goal-intent
  sidecar, so the ledger and the sidecar can never disagree about whether a
  goal is live.
- A regression test that fails against the current code: retire the last live
  plan, assert the sidecar is gone rather than merely unchanged.
- Removal is best-effort and never raises, matching `write_goal_signal`'s
  contract — a sensor signal must not break the tool call that triggered it.

## Non-Goals

- Changing when goals are EMITTED, or the combined-goal rendering for the
  multi-live-plan case. The write path is correct; only the retract path is
  missing.
- Teaching the Stop handler to validate that a goal's plan path exists. That
  would mask this defect rather than fix it, and a goal naming a real plan
  that just retired is equally stale.
- Stopping acceptance fixtures from writing to the operational ledger. Real,
  and worth its own plan — see Task 2.1.

## Tasks

### Phase 1: Retract the sidecar when the ledger empties

- [x] ✅ **Task 1.1**: RED — `test_retiring_the_only_live_plan_removes_the_signal`
  failed against the pre-fix code with the sidecar still present, exactly as
  predicted.
- [x] ✅ **Task 1.2**: GREEN — `clear_goal_signal(session_id)` added beside
  `write_goal_signal`, `unlink(missing_ok=True)` under the same
  `RuntimeError`/`OSError` best-effort contract, called from the
  `fallback is None` branch.
- [x] ✅ **Task 1.3**: `test_retirement_leaves_signal_intact_while_another_plan_stays_live`
  pins the boundary: retiring one of two live plans still rewrites the signal
  and keeps naming the survivor. It passed before and after the fix, so the
  retraction is scoped to an empty ledger only.

### Phase 2: Follow-ups

- [ ] ⬜ **Task 2.1**: Acceptance fixtures write goals for a fixture plan
  (`CLAUDE/Plan/00099-test`) into the OPERATIONAL ledger and sidecar. Even with
  Phase 1 fixed, a fixture run mid-session emits a real goal for a plan folder
  that does not exist. Decide whether fixtures should be pointed at a temp
  ledger, and file separately if the change is larger than a test-fixture edit.

## Success Criteria

- [x] The Phase 1 regression test fails against the pre-fix code and passes
  after, verified by running it at both commits.
- [x] After a retirement that empties the ledger, no `.goal-intent` file remains
  for that session.
- [x] `./scripts/qa/llm_qa.py all` passes 25/25 (17,291 passed, 95.2%).
- [ ] Task 2.1 (acceptance fixtures writing goals for a non-existent fixture
  plan into the operational ledger) is decided — the only item keeping this
  plan open.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00320-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
