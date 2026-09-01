# Plan 00298: failsafe cron blockage cadence

**Status**: Not Started
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

- Not implementing daemon source changes in this plan — this plan is
  design/brainstorm only (BRAINSTORM.md + this spec). Implementation is a
  follow-on plan once the approach is reviewed.
- Not changing the cron's cadence for genuine external-interruption recovery
  (stays hourly) — only the human-input-blocked no-op case is addressed.
- Not attempting session-side/convention-only backoff (BRAINSTORM.md ideas 1
  and 4) as the primary mechanism — evaluated and rejected in favour of the
  deterministic daemon-side approach; kept only as a documented fallback.

## Tasks

### Phase 1: Design review

- [ ] ⬜ **Task 1.1**: Owner reviews BRAINSTORM.md's recommendation
  (blocked-state marker on Stop + UserPromptSubmit suppression keyed on the
  canonical cron prompt, bounded marker expiry) and confirms or redirects
  the approach.

### Phase 2: Implementation (follow-on plan)

- [ ] ⬜ **Task 2.1**: File a new plan (once Phase 1 is confirmed) scoped to
  the actual daemon-side implementation: the Stop-handler marker, the
  narrow "blocked on human input" pattern set, the `UserPromptSubmit`
  suppression handler, and the marker expiry. Kept separate from this
  design plan per the daemon-source-editing restriction and to keep this
  plan's scope reviewable on its own.

## Success Criteria

- [ ] BRAINSTORM.md's idea list and recommendation reviewed and confirmed
  (or redirected) by the owner.
- [ ] A follow-on implementation plan filed and linked from this plan once
  confirmed.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00298-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
