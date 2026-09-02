# Plan 00314: failsafe cron suppression marker never arms

**Status**: Not Started
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single python-developer agent, TDD

## Overview

Live dogfood observation (v3.59.0 release session, night of 2026-09-01→02):
four hourly failsafe-cron ticks all reached the model as full turns while the
session was verifiably blocked only on human input. The Plan 00298
suppression (`failsafe_cron_blockage_suppressor` reading the marker written
by `auto_continue_stop._maybe_record_human_blocked_marker`) never engaged
because the marker file was never created.

Two distinct defects observed:

1. **Marker write silently failed on a MATCHING phrase.** The 01:28 UTC stop
   message contained the literal pattern-1 phrase "blocked only on human
   input", the Stop verdict log shows `auto-continue-stop allow` (the branch
   that calls the marker writer), yet
   `untracked/human-input-blockage-marker.json` does not exist. Every
   failure path in the writer is fail-open (`logger.debug`/`warning`), and
   the daemon's 1,000-record in-memory log ring had rolled past the window
   before inspection — so the root cause is currently unknown and the
   failure class is invisible in the field.
2. **`_HUMAN_BLOCKED_PATTERNS` misses natural phrasings.** Real stop
   messages from the same night said "blocked on human input" (no "only")
   and "waiting only on human input" — neither matches: pattern 4's
   alternation allows `owner|user` but not `human`, inconsistently with
   pattern 1 which is human-only.

## Goals

- Reproduce defect 1 with a TDD test driving the real Stop-handler path
  (transcript fixture whose current-turn message carries the exact 01:28
  shape, including the em-dash and parenthetical) and fix the root cause.
- Make marker-write failure observable after the fact: record a
  `marker_written` outcome in stop-events.jsonl so "matched but not armed"
  is diagnosable in the field without the volatile log ring.
- Widen `_HUMAN_BLOCKED_PATTERNS` conservatively: accept `human` alongside
  `owner|user` in the waiting-pattern; decide (and document at the pattern
  table) whether `blocked on human input` without "only" can be accepted
  without arming on transient mentions.
- Live re-verification: a real session stop with the phrase arms the marker
  (file exists, correct session id) and the next delivered cron tick is
  denied by `R-FAILSAFE-CRON-SUPPRESSED`.

## Non-Goals

- Changing the 24h expiry, the marker file format, or the fail-open
  philosophy (owner ruling on 00298: minimal and brittle-free).
- Any change to the cron itself or its canonical prompt.

## Tasks

### Phase 1: Reproduce and fix

- [ ] ⬜ **Task 1.1**: RED — transcript-fixture test reproducing the 01:28
  stop shape through `AutoContinueStopHandler.handle`; assert the marker
  file exists afterwards. Confirm it fails against current code (or, if it
  passes, escalate instrumentation until the live divergence is explained —
  candidate suspects: `_resolve_current_turn_message` freshness resolution,
  `_message_text` block concatenation, session_id absence in the live Stop
  payload, ProjectContext resolution inside the daemon process).
- [ ] ⬜ **Task 1.2**: GREEN — fix the root cause; add the stop-events.jsonl
  `marker_written` field for field observability.
- [ ] ⬜ **Task 1.3**: Pattern widening with tests (`human` in the waiting
  pattern; decide and document the no-"only" question).
- [ ] ⬜ **Task 1.4**: Full QA green; live dogfood — arm the marker with a
  real stop, observe the next cron tick suppressed, record evidence in
  JOURNAL/.

## Success Criteria

- [ ] Marker file reliably appears after a matching STOPPING BECAUSE stop
  (unit-pinned AND observed live).
- [ ] A delivered cron tick while the marker is live is denied
  (`R-FAILSAFE-CRON-SUPPRESSED`) — observed live.
- [ ] QA 25/25.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00314-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
