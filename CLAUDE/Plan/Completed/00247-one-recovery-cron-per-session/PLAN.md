# Plan 00247: Exactly One Failsafe Recovery Cron Per Session

**Status**: Complete
**Created**: 2026-08-17
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Dogfooding report: the daemon's own `recovery_cron_advisor` handler causes
STACKED failsafe recovery crons. Its creation-phase advisory says "Create a
non-durable hourly failsafe recovery cron NOW" with no instruction to look for
one first, so every plan created in a session produces another cron — all
identical, all on the same minute, all firing on the same session.

Observed live in the session that filed this plan: three prompts, two crons
(`8326de0b` and `f12d9c0d`, both hourly at `:23`) before the duplicate was
noticed and deleted by hand. The advisory then fired a third time while filing
THIS plan, with one cron already running.

The invariant the user states, and which this plan implements: **there should be
only one.** Never stack; reuse the one that exists, or drop and recreate it.

## The defect is an unimplemented decision, not a new idea

`recovery_cron_advisor.py`'s own module docstring already claims this:

> Decision D2 (PLAN.md): … The agent uses CronList to avoid duplicate creates.

Plan 00139 (Complete) established that. The handler cites it and then does not
do it: `CronList` appears only in the PROGRESS guidance, and even there it says
"recreate if missing" — nothing about more than one existing. The text an agent
actually reads at creation time never mentions looking first.

One cron is sufficient by construction, which is why stacking is pure cost: the
canonical prompt is plan-agnostic ("your most recent work on the active
plan/task"), so a single cron already covers every plan in the session.

## Goals

- The creation advisory can never produce a second cron: check `CronList` first,
  reuse what is there, create only when none exists.
- The progress advisory REPAIRS an already-stacked session by collapsing extras
  to one.
- `get_claude_md()`'s resident lifecycle table says the same thing, so the copy
  read first does not contradict the advisory.
- A test fails if any of those instructions is reworded away.

## Non-Goals

- Changing the cron's schedule, its non-durable nature, or the canonical prompt.
- Making the daemon manage crons itself. It cannot: `CronCreate`/`CronList` are
  Claude Code tools, so the handler can only advise. This plan fixes the ADVICE.
- Revisiting Plan 00139's decisions. D2 is right; it was never implemented.

## Tasks

### Phase 1: Fix the guidance the agent reads

- [x] ✅ **Task 1.1**: Failing tests for the one-cron invariant (RED)
  - [x] ✅ Creation guidance names `CronList`, gates the create, says reuse, and
    states the invariant
  - [x] ✅ Progress guidance names `CronDelete` and the duplicate case
  - [x] ✅ `get_claude_md()` table agrees with the advisory
- [x] ✅ **Task 1.2**: Rewrite `_CREATION_GUIDANCE` as check-first (GREEN)
- [x] ✅ **Task 1.3**: Extend `_PROGRESS_GUIDANCE` to collapse duplicates to one
- [x] ✅ **Task 1.4**: Update the `get_claude_md()` lifecycle table to match

### Phase 2: The sibling advisory

- [x] ✅ **Task 2.1**: Audit `background_process_tracker`'s watchdog-cron
  guidance for the same unconditional-create shape, and fix it the same way if
  present
  - [x] ✅ Present and fixed — its advisory said "Create a non-durable recurring
    watchdog cron" unconditionally, and it fires on EVERY backgrounded process,
    so it stacked faster than the recovery advisory did

### Phase 3: Verify

- [x] ✅ **Task 3.1**: Full QA suite green (23/23; black auto-fixed the two test
  files mid-run and re-ran clean, 12434 tests, coverage 95.1%)
- [x] ✅ **Task 3.2**: Daemon restart RUNNING, and the advisory's live text
  confirms check-first (probe the running daemon, not just the unit tests)
  - [x] ✅ Probed `.claude/hooks/post-tool-use` with a synthetic plan-creation
    payload: the running daemon emits "CronList FIRST" and "EXACTLY ONE"
  - [x] ✅ Then dogfooded for real — the fixed advisory fired on a journal write
    and told me to check first; the existing cron was reused, none created

## Dependencies

- Related: Plan 00139 (Failsafe Recovery Cron, Complete) — this implements its
  Decision D2, which the handler cites but never enforced.

## Technical Decisions

### Decision 1: fix the advice, not the mechanism

**Context**: the daemon cannot dedupe crons itself — `CronList`, `CronCreate`
and `CronDelete` are Claude Code tools available to the agent, not daemon APIs.

**Decision**: the only lever is the text the agent reads, so the guidance must
carry the whole invariant: look first, reuse, create only when absent, and
collapse extras when found. A test asserts each of those four instructions is
present, because guidance text is the kind of thing a later reword silently
erodes — which is exactly how Plan 00139's D2 came to be claimed but not done.

**Date**: 2026-08-17

## Success Criteria

- [x] Creating a second plan in a session advises REUSING the existing cron
- [x] An already-stacked session is repaired by the progress advisory
- [x] Resident `CLAUDE.md` guidance and the injected advisory agree
- [x] QA green, daemon restart RUNNING

## Risks & Mitigations

| Risk                                             | Impact | Probability | Mitigation                                                              |
| ------------------------------------------------ | ------ | ----------- | ----------------------------------------------------------------------- |
| Longer guidance is skimmed and the check missed  | Medium | Medium      | Put `CronList` in the FIRST step and gate the create step on its result |
| Agent deletes its only cron while work continues | High   | Low         | Keep the existing "deleting leaves you uncovered" warning intact        |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed, delivered and archived in one sitting. The regenerated `CLAUDE.md`
  handler guidance was auto-committed by the daemon at `ca4b0599` on restart, so
  the SOURCE behind it — both handlers, their tests and this plan — lands in the
  next commit, the one that archives this folder into `Completed/`.
- Verified live, not just in tests: the fixed progress advisory fired while this
  plan was being closed, told me to run `CronList` first, and the single existing
  cron (`8326de0b`) was reused rather than stacked.
