# Plan 00393: niggles ledger seven

**Status**: Complete
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

- [x] ✅ **N1** — GRADUATED to [Plan 00394](../../00394-failsafe-cron-coverage-starts-at-first-plan-write/PLAN.md).
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

  **Why the omission matters.** Plan 00384 built `persistent_crons` *because*
  `CronCreate` cannot persist a job — `durable` has no effect and recurring jobs
  expire after 7 days. The mechanism exists to make a wanted cron survive the
  start of a new session. The failsafe recovery cron is the one whose absence is
  least visible and most costly: it is the net that resumes a session stalled by
  a rate limit, an API error or a usage limit. If a new session starts and the
  agent does not act on `recovery_cron_advisor`'s output, there is no recovery
  coverage at all, and nothing reports that — the symptom is a session that
  simply never resumes.

  **The counter-argument, recorded so the ruling is made on both.** The failsafe
  prompt is already daemon-authored verbatim by `recovery_cron_advisor`, and the
  watchdog is deliberately agent-composed (Plan 00388 records exactly this
  three-way provenance split). Declaring the watchdog would mean fixing wording
  the daemon currently leaves open on purpose, so the two are not one decision.

  **Diagnosed, and it is why this graduated rather than being fixed here.** The
  entry opened on the hypothesis that the omission was an oversight, and reading
  Plan 00384 overturned that: it considered the failsafe cron and justified
  leaving it out — "`recovery_cron_advisor` already establishes this shape for
  the failsafe cron." Half of that holds. The advisor does supply a
  daemon-authored verbatim prompt, but "this shape" was defined in the same
  sentence as *asserting at SessionStart*, and the advisor is a PostToolUse
  handler gated on a plan-lifecycle moment:

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

- [x] ✅ **N2** — FIXED at `ed00e582`. CI on `main` cancelled its own runs,
  destroying the evidence two documented mechanisms depend on.

  **Observed**: 13 of the last 20 CI runs concluded `cancelled`, including three
  consecutively while closing plans in one session:

  ```text
  ee4aab64  in_progress
  bbe5b331  cancelled   <- killed by the ee4aab64 push
  a83593eb  cancelled   <- killed by the bbe5b331 push
  20511016  cancelled   <- killed by the a83593eb push
  836164e9  success     <- survived only because nothing followed it for 20 min
  ```

  **Cause**, `.github/workflows/qa.yml:10-12`: `concurrency.group` is
  `qa-${{ github.ref }}`, which is `refs/heads/main` for EVERY push to main, with
  `cancel-in-progress: true`. So each push killed the previous run.

  **Why it is a defect here and not a sensible default.** Cancelling superseded
  runs is correct when only the newest commit matters. Two mechanisms in this
  repository need the opposite: Plan 00359's `release-slate-check` requires
  HEAD's EXACT sha to be CI-green, and plan completion criteria cite a specific
  commit. Combined with the standing authorisation to push after each logical
  unit, the configuration and the workflow were in direct conflict — the rule
  that says "never hold a push" guaranteed the destruction of the evidence the
  release gate needs.

  **Fix**: `cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}`. A push
  to main now QUEUES behind a running job instead of killing it; a PR branch
  keeps the cheap behaviour. Free on this repository — it is public, so standard
  runners are not metered.

  **CORRECTION — an earlier revision of this entry overclaimed the result.** It
  said the fix means "every sha gets a result". That is false and was written
  without being checked. Observed four pushes later:

  ```text
  8682b3df  pending       <- newest, queued
  268cbc77  cancelled     <- was pending, superseded
  57d6b435  cancelled     <- was pending, superseded
  a64dca90  in_progress   <- RUNNING, survived all three pushes
  ```

  What the fix actually guarantees is narrower and is still the thing that
  mattered: **a RUNNING job is never killed**, so a run that starts, finishes.
  Queued runs are still superseded — only the newest pending run per concurrency
  group survives. Intermediate commits on main therefore may still have no CI
  result.

  That is acceptable for the defect this entry was about, because Plan 00359's
  gate needs HEAD's exact sha to be green and HEAD is always the newest pending
  run, which does execute. It is NOT acceptable as a description, which is why
  the claim is corrected here rather than left to mislead the next reader. The
  precise mechanism for the pending-run supersession is GitHub's own concurrency
  behaviour and is stated here as the explanation for what was observed, not as
  something this plan verified against the documentation.

  **Verified in production, which is the only way this one can be tested.**
  `ee4aab64` completed `success` despite `ed00e582` being pushed on top of it —
  the first run on main to survive a following push. The line directly below it
  in the same listing, `bbe5b331`, was cancelled by exactly that sequence under
  the old config. `ed00e582` then queued and ran rather than pre-empting it.

  **The trade-off, stated rather than buried**: runs on main now serialise, so
  wall-clock time to a result grows when several pushes land together. That is
  the right trade because a fast result that is destroyed before anything reads
  it has no value, but it is a real cost and not a free win.

## Success Criteria

- [x] Every entry above is either fixed with a regression test, or graduated to
  a named plan and that plan is linked from the entry. N1 graduated to Plan
  00394; N2 fixed at `ed00e582`, whose verification is observational because a
  workflow's concurrency behaviour cannot be exercised by a unit test.
- [x] No entry is closed on reasoning alone. N1's diagnosis was read out of the
  handler directories and `matches()` rather than inferred from docstrings, and
  it overturned the hypothesis the entry opened with. N2 was measured (13 of 20
  runs cancelled) and its fix confirmed by a run that survived a following push.
- [x] This plan's one code change has no release-bound consequence:
  `.github/workflows/` is repo-internal CI and is not deployed to client
  projects — checked against `scripts/install.sh` and `scripts/upgrade.sh`,
  whose only `.github` references are download URLs. Nothing a client installs
  or runs is different, so the holding area gets no note.
- [x] Full QA passes and CI is green. Full QA 29/29 PASSED and CI concluded
  `success` on `ed00e582` — the exact commit this closes on.

## Delivery & Milestones

- Opened because ledger 00392 closed when its entry was resolved and a new
  niggle was found, per the SOP in `CLAUDE/core/PlanWorkflow.core.md`: "The next
  niggle found opens a NEW ledger. Never reopen a closed one."
- **Close this ledger when its entries are resolved.** Do not hold it open as a
  standing fixture, and do not hold it open to accumulate a fuller set — a
  one-entry ledger that closes is working correctly.
- Both entries are resolved, so this ledger closes. The next niggle runs
  `mkplan.bash` for ledger eight rather than reopening this one.
- Worth recording for whoever reads this next: neither entry was found by the
  work the session set out to do. N1 came from a question the owner asked about
  crons, and N2 from a hook challenging a hedge in an earlier message. Both had
  been sitting in plain sight for the whole session.
