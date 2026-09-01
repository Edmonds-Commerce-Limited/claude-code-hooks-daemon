# Plan 00298: failsafe cron blockage cadence

**Status**: Complete
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner's incident report (2026-08-31 → 09-01): Plan 00297 finished and the
session became blocked **only** on two pending owner decisions — a stable
state, not a transient stall. The hourly failsafe recovery cron (managed via
`recovery_cron_advisor`, `src/claude_code_hooks_daemon/handlers/post_tool_use/recovery_cron_advisor.py`,
canonical prompt in `_CANONICAL_CRON_PROMPT`) then fired ~14 consecutive
times overnight. Each tick cost a full model turn whose entire output was a
guaranteed no-op: `STOPPING BECAUSE: failsafe cron tick, nothing to resume ... blocked only on human input. Waiting.` — cleanly allowed by
`auto_continue_stop.py` Branch 2, so there is no deny-loop; the waste is
purely the per-tick model turn itself. Owner's framing: "once we hit a full
blockage [the cron is] just token burning for the sake of it."

The cron exists to recover from **external** interruptions (API error, rate
limit, 5-hour usage limit, network failure). A session blocked only on human
input is not that state, and the transition into it is already narrated
every time by the model's own `STOPPING BECAUSE:` text — so it is a
well-defined, detectable state, not a fuzzy heuristic. See
[BRAINSTORM.md](BRAINSTORM.md) for the full idea list, trade-offs, and the
recommendation this plan's tasks implement: a daemon-side blocked-state
marker recorded by the Stop handler, consumed by a `UserPromptSubmit`
suppression check keyed on the canonical cron prompt text, with a bounded
expiry as the safety valve against over-suppression.

## Goals

- A session that is stably blocked only on human input consumes **zero**
  model turns from failsafe cron ticks, deterministically (daemon-enforced,
  not convention/prompt-text).
- A session recovering from a genuine external interruption (API error, rate
  limit, network failure) still recovers within one cron interval — no
  suppression regression on the case the cron exists for.
- The blocked-state marker degrades safely: an extended silence (bounded
  expiry) returns the session to full hourly coverage automatically, so a
  stale marker cannot suppress a real recovery indefinitely.

## Non-Goals

- Not changing the cron's cadence for genuine external-interruption recovery
  (stays hourly) — only the human-input-blocked no-op case is addressed.
- Not attempting session-side/convention-only backoff (BRAINSTORM.md ideas 1
  and 4) as the primary mechanism — evaluated and rejected in favour of the
  deterministic daemon-side approach; kept only as a documented fallback.

## Tasks

### Phase 1: Design review

- [x] ✅ **Task 1.1**: Owner reviews BRAINSTORM.md's recommendation
  (blocked-state marker on Stop + UserPromptSubmit suppression keyed on the
  canonical cron prompt, bounded marker expiry) and confirms or redirects
  the approach. **Owner ruling**: approved for implementation, with a
  brittleness caveat ("sounds complex and brittle to me") — implementation
  built the MINIMAL version (one marker, one session-scoped validity check,
  no fallback chains) with every failure mode failing OPEN, per that ruling.

### Phase 2: Implementation

- [x] ✅ **Task 2.1**: `blockage_marker` utility (shared primitive): a small
  JSON marker file (`session_id` + `recorded_at`) under the daemon's
  untracked dir, with fail-open write/read/clear and a session-scoped
  expiry check.
- [x] ✅ **Task 2.2**: `auto_continue_stop.AutoContinueStopHandler` Branch 2
  records the marker when the resolved `STOPPING BECAUSE:` text matches a
  narrow, enumerated "blocked only on human input" pattern set (never a
  broad "input" substring match) — a false-positive guard named in
  BRAINSTORM.md is covered by a dedicated regression test.
- [x] ✅ **Task 2.3**: `failsafe_cron_blockage_suppressor` (new
  `UserPromptSubmit` handler): recognises a delivered canonical-cron-prompt
  tick (matched via a shared `CANONICAL_CRON_PROMPT_MARKER` constant
  exported from `recovery_cron_advisor`, not a duplicated string) and, while
  a still-valid marker exists for the session, blocks it before the model
  ever sees it — zero-token, not just cheaper. Never terminal, so
  `idle_housekeeping_advisory` and `standing_authorisations` (which key off
  the same canonical prompt) still run on every non-suppressed tick.
- [x] ✅ **Task 2.4**: Any genuine (non-cron) user prompt needs no dedicated
  clearing code — the marker is only ever consulted against the DELIVERED
  cron-prompt shape, so a real prompt simply never matches
  `failsafe_cron_blockage_suppressor.matches()` and proceeds normally; the
  marker's own expiry (`expiry_hours`, default 24) is the sole other exit.
- [x] ✅ **Task 2.5**: Documentation — `docs/guides/HANDLER_REFERENCE.md`
  entries for both touched handlers (new suppressor + the marker addendum
  on `auto_continue_stop`); `check_handler_reference.py` passes.

## Success Criteria

- [x] BRAINSTORM.md's idea list and recommendation reviewed and confirmed
  by the owner (with the brittleness caveat above).
- [x] A session that is stably blocked only on human input consumes zero
  model turns from failsafe cron ticks (dogfooding acceptance: this
  repo/session runs the exact cron).
- [x] Every failure mode (unreadable/corrupt/stale marker, no project
  context, missing session_id, pattern miss) fails OPEN — the tick reaches
  the model as before, pinned by dedicated tests on both handlers.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00298-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
