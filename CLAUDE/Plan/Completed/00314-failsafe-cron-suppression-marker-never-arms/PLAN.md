# Plan 00314: failsafe cron suppression marker never arms

**Status**: Complete
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

- [x] ✅ **Task 1.1**: Shipped in `923fd583`. The RED reproduction PASSED
  against current code and all four named suspects were ruled out, so the
  escalation branch of this task applied: the live divergence has no
  reproducible cause, and the response was to make the failure class visible
  rather than to guess at a fix.
- [x] ✅ **Task 1.2**: Shipped in `923fd583`. `write_marker` returns its
  outcome and stop-events.jsonl carries `marker_written`, so "matched but not
  armed" is now diagnosable from disk instead of from a log ring that had
  already rolled.
- [x] ✅ **Task 1.3**: Shipped in `923fd583`. Pattern 4 accepts `human`
  alongside `owner|user`.
- [x] ✅ **Task 1.4**: **Closed on evidence, with one half unit-pinned rather
  than observed.** Arming is proven live: `untracked/stop-events.jsonl`
  carries 16 records with `"marker_written": true`, the field this plan added
  for exactly this purpose. The suppression half — a delivered tick denied by
  `R-FAILSAFE-CRON-SUPPRESSED` — is NOT directly evidenced in what survives on
  disk, because the daemon's log ring rolls and today's restarts cleared it. It
  is covered by 22 unit tests including
  `test_cron_prompt_with_valid_marker_is_still_denied`. Recorded as-is rather
  than claimed as a live observation.

## Success Criteria

- [x] Marker file reliably appears after a matching STOPPING BECAUSE stop
  (unit-pinned AND observed live — 16 `marker_written: true` records).
- [x] A delivered cron tick while the marker is live is denied
  (`R-FAILSAFE-CRON-SUPPRESSED`) — unit-pinned by 22 tests. NOT observed live:
  the surviving logs do not carry it, and the criterion is recorded as met by
  test rather than by observation rather than being quietly ticked.
- [x] QA 25/25.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00314-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Delivery: `923fd583` (Tasks 1.1–1.3) plus the archiving commit.
- **Closed out late, by Plan 00337 Phase 1.** The work shipped on 2026-09-02
  and this document was never updated — the executor journalled the commit but
  left every box `⬜` and the status `Not Started`. A plan that reads Not
  Started when its work has shipped invites a second agent to redo it, which
  is why 00337 made correcting the record its own first phase rather than a
  footnote.
- **What did NOT ship**: nothing further is queued here. 00337 Task 3.4
  supersedes the idea of another round of pattern widening — the mechanism
  moves to an explicit declaration instead, and `_HUMAN_BLOCKED_PATTERNS`
  stays only as a compatibility fallback.
