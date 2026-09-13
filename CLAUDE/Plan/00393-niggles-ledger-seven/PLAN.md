# Plan 00393: niggles ledger seven

**Status**: In Progress
**Created**: 2026-09-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The open ledger for small defects. Ledger six (00392) closed when its single
entry was resolved by graduation, and SOP is that the next niggle found opens a
NEW ledger rather than reopening an archived one — so this exists because a
niggle was found, not in anticipation of one.

A niggle is recorded **in the turn it is found**, before the work that surfaced
it continues. The rule exists because the alternative is reporting it in context
output, where it is read once and then lost when the window compacts. Every
entry names what was OBSERVED, not what was guessed.

Entries may be fixed here, or GRADUATED to their own plan when they turn out to
be larger than a niggle. Graduating is a success: the ledger's job is to make
sure nothing is dropped, not to force every fix into one plan.

## Goals

- Every small defect found while doing other work is recorded, with enough
  evidence that someone else could reproduce it.
- Each entry is either fixed here or graduated to a named plan — never dropped.

## Non-Goals

- Batching. An entry is appended the turn it is found; the ledger is never
  "caught up" later from memory.
- Large work. Anything needing its own design graduates to its own plan.

## Tasks

### Phase 1: Entries

- [x] ✅ **N1** — GRADUATED to [Plan 00394](../00394-failsafe-cron-coverage-starts-at-first-plan-write/PLAN.md).
  The FAILSAFE recovery cron is the one cron `persistent_crons` does not
  declare, and it is the most safety-critical of the three.

  **Observed.** `persistent_crons.jobs` in `.claude/hooks-daemon.yaml:1025-1037`
  declares exactly one job:

  ```text
  persistent_crons.jobs:
    - id: issue-sdlc      schedule "23 * * * *"    <- declared
    (failsafe recovery)   schedule "17 * * * *"    <- NOT declared
    (background watchdog) schedule "41 * * * *"    <- NOT declared
  ```

  All three were live in this session. Only `issue-sdlc` has config backing;
  the other two exist because an agent acted on an advisory.

  **Why this looks like an oversight rather than a design choice.** Plan 00384
  built `persistent_crons` *because* `CronCreate` cannot persist a job —
  `durable` has no effect and recurring jobs expire after 7 days. The mechanism
  exists to make a wanted cron survive the start of a new session. The failsafe
  recovery cron is the one whose absence is least visible and most costly: it is
  the net that resumes a session stalled by a rate limit, an API error or a
  usage limit. If a new session starts and the agent does not act on
  `recovery_cron_advisor`'s output, there is no recovery coverage at all, and
  nothing reports that — the symptom is a session that simply never resumes.

  **The counter-argument, recorded so the ruling is made on both.** The failsafe
  prompt is already daemon-authored verbatim by `recovery_cron_advisor`, and the
  watchdog is deliberately agent-composed (Plan 00388 records exactly this
  three-way provenance split). Declaring the watchdog would mean fixing wording
  the daemon currently leaves open on purpose, so the two are not one decision.

  **Diagnosed, and it is why this graduated rather than being fixed here.** It
  was a reasoned decision, not an oversight. Plan 00384 considered the failsafe
  cron and justified leaving it out: "`recovery_cron_advisor` already
  establishes this shape for the failsafe cron." Half of that holds — the
  advisor does supply a daemon-authored verbatim prompt — but "this shape" was
  defined in the same sentence as *asserting at SessionStart*, and the advisor
  is a PostToolUse handler gated on a plan-lifecycle moment:

  ```text
  persistent_cron_assertor  -> handlers/session_start/   fires every session
  recovery_cron_advisor     -> handlers/post_tool_use/   fires on a plan write
  grep failsafe|recovery handlers/session_start/  -> no match
  ```

  So coverage begins at the first plan-file write, not at session start, and any
  stall before that is uncovered with no symptom other than a session that never
  resumes. Graduated because the fix is an owner call between three options with
  materially different blast radii — a config edit to this repo, a new
  SessionStart handler, or a daemon-default declared job — and because it means
  correcting a claim in an archived plan.

  **How it was found.** Investigating whether a terminal crash had exercised the
  cron declaration machinery. It had not — the session was RESUMED, not
  restarted, so all three crons came back with identical IDs and no `CronCreate`
  call. Chasing why "session-only" had not bitten is what exposed that two of
  the three crons have no declaration to fall back on when it eventually does.

## Success Criteria

- [ ] Every entry above is either fixed with a regression test, or graduated to
  a named plan and that plan is linked from the entry.
- [ ] No entry is closed on reasoning alone: each names what was OBSERVED, with
  evidence someone else could re-check.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  this plan records why it has none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Opened because ledger 00392 closed when its entry was resolved and a new
  niggle was found, per the SOP in `CLAUDE/core/PlanWorkflow.core.md`: "The next
  niggle found opens a NEW ledger. Never reopen a closed one."
- **Close this ledger when its entries are resolved.** Do not hold it open as a
  standing fixture, and do not hold it open to accumulate a fuller set — a
  one-entry ledger that closes is working correctly.
