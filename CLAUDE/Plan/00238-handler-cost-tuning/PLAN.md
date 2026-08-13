# Plan 00238: Handler Cost Tuning

**Status**: In Progress
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

[Plan 00234](../00234-handler-value-audit/PLAN.md) Task 4.8 — "Follow-up H",
the last of its eight proposals and the one it ranked lowest-urgency. Every
handler here is WANTED and does its job; the finding is that several pay a cost
far above what their duty requires, and in two cases the cost is an accident of
one constant sitting on the wrong side of a threshold.

This is deliberately NOT a removal plan. Plan 00237 removed the handlers that
earned removal; these five earned a verdict of FIX or SUSPECT, which means the
behaviour stays and the cost changes. A tuning change that alters observable
behaviour has failed, and each task below names what must stay identical.

The headline is `git_branch`, and it is worth stating precisely because it is
counter-intuitive: its render-TTL cache is not weak, it is RESONANT. The TTL is
2.0s and the measured render interval is ~1.15s. Because `1.15 < 2.0 < 2.30`,
every render alternates hit, miss, hit, miss — an exact 50% miss rate, forever,
by construction rather than by chance. A cache that looks like it is working is
halving a cost it could nearly eliminate.

## Goals

- Cut the status line's measured subprocess and file-I/O rate without changing
  a single rendered character in the steady state
- Fix the two resonance defects (`git_branch` render TTL, `supervisor_indicator`
  negative-cache TTL) by choosing constants RELATIVE to the render interval
  rather than as absolute seconds that silently drift into resonance
- Give `git_context_injector` and `daemon_restart_verifier` the change-detection
  and rate-limiting their FIX verdicts call for, without weakening either duty
- Leave behind a way to NOTICE resonance, not just this instance of it

## Non-Goals

- Removing or disabling any handler in this plan — all five are wanted
- Re-litigating Plan 00234's verdicts; only a measurement that contradicts one
- Changing what the status line DISPLAYS (a tuning change that alters output is
  a bug, not a tuning)
- A general caching framework — YAGNI; `settings_reader.py` already
  demonstrates the mtime-gate pattern in this exact directory

## Context & Background

Measured evidence is in Plan 00234's
[RESEARCH-F-statusline.md](../00234-handler-value-audit/RESEARCH-F-statusline.md)
and [VERDICTS.md](../00234-handler-value-audit/VERDICTS.md). Live numbers, from
a 65-minute window: ~3,130 renders/hour, ~1.15s render interval.

| Handler                   | Verdict | Measured cost                                                                                                             |
| ------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------- |
| `git_branch`              | SUSPECT | ~50% TTL miss ⇒ **~6,200 git subprocess spawns/hour** — the largest single source in the whole chain                      |
| `supervisor_indicator`    | SUSPECT | full `/proc` walk on a negative-cache miss; 5s TTL vs 1.15s renders ⇒ a walk every ~4–5 renders for a project WITHOUT ccy |
| `account_display`         | SUSPECT | 1 uncached read + regex **every render, forever** — the only file-reading handler in the cohort with no cache of any kind |
| `git_context_injector`    | FIX     | ~460-token minimum payload on **every** prompt, zero change-detection                                                     |
| `daemon_restart_verifier` | FIX     | the same paragraph reaches context three ways on **every** commit, no rate limit                                          |

Two things the research found that this plan must respect:

1. **This repo does not feel `supervisor_indicator`'s cost.** ccy is armed
   here, so the positive cache holds and the `/proc` walk is not paid on the
   measured renders. The cost is real for projects that never run the
   supervisor — which is most of them. Measuring locally will show nothing; the
   fix must be verified against a forced negative-cache path.
2. **`account_display` is not alone.** The research names four handlers with
   the same uncached-read-every-render shape: `account_display`,
   `upgrade_notifier`, `startup_cleanup`, and (bounded by small N)
   `multithread_indicator` — collectively ~9,000–12,500 avoidable file
   operations/hour. Follow-up H named only the first. Fixing one and leaving
   three is the "95 instances by hand" failure DBF exists to prevent.

## Tasks

### Phase 1: Establish the baseline before changing anything

- [ ] ⬜ **Task 1.1**: Measure the CURRENT render interval on this machine
  rather than inheriting ~1.15s from the research. The resonance argument is
  entirely a function of that number, so a stale value invalidates every TTL
  choice below
- [ ] ⬜ **Task 1.2**: Capture a baseline count of git subprocess spawns and
  status-line file reads over a fixed window, by a method that can be re-run
  identically afterwards. A before/after with different methodology proves
  nothing

### Phase 2: The two resonance defects

- [ ] ⬜ **Task 2.1**: `git_branch` — widen `_DEFAULT_RENDER_TTL_SECONDS` past
  the resonance point. The staleness budget is already far looser elsewhere in
  the same handler (the background fetch TTL is 300s), so a few seconds of icon
  staleness is well inside what the design already accepts. Derive the value
  from the measured render interval; do not pick a round number
- [ ] ⬜ **Task 2.2**: `supervisor_indicator` — bound the negative-path `/proc`
  walk. The 5s negative-cache TTL has the same resonance shape against a ~1.15s
  render interval. Prefer bounding the WALK itself (it reads `cmdline` for
  every numeric pid on the box) over only widening the TTL, since the TTL only
  changes how often the unbounded thing happens
- [ ] ⬜ **Task 2.3**: DBF — a constant chosen relative to the render interval
  can drift back into resonance the moment either number moves, and nothing
  would report it. Add a guard that fails when a render-path TTL sits inside
  the resonance band for the configured refresh interval

### Phase 3: The uncached-read family

- [ ] ⬜ **Task 3.1**: mtime-gate `account_display`, reusing the existing
  pattern in `settings_reader.py` rather than inventing a second one
- [ ] ⬜ **Task 3.2**: Apply the same gate to the three siblings the research
  named — `upgrade_notifier`, `startup_cleanup`, `multithread_indicator` — or
  record per handler why it does not apply. Follow-up H named only
  `account_display`; fixing one of four is the shape DBF exists to prevent
- [ ] ⬜ **Task 3.3**: Verify the rendered output is byte-identical before and
  after for every handler touched. A caching change that alters the line has
  changed behaviour, not cost

### Phase 4: The two FIX verdicts off the status line

- [ ] ⬜ **Task 4.1**: `git_context_injector` — inject only on CHANGE. The duty
  (git state informs decisions) is wanted; re-sending an unchanged ~460-token
  payload on every prompt is not. Decide and record what "changed" means, since
  a too-strict definition silently stops informing
- [ ] ⬜ **Task 4.2**: `daemon_restart_verifier` — rate-limit per session. The
  research found the same paragraph reaching context three ways on every
  commit; establish which of the three is worth keeping before adding a limiter
  to all three

### Phase 5: Verification

- [ ] ⬜ **Task 5.1**: Re-measure with Task 1.2's method and record before/after
- [ ] ⬜ **Task 5.2**: Full QA — `./scripts/qa/llm_qa.py all`
- [ ] ⬜ **Task 5.3**: Daemon restart verified RUNNING; status line unchanged
- [ ] ⬜ **Task 5.4**: Commit and push

## Dependencies

- Depends on: [Plan 00234](../00234-handler-value-audit/PLAN.md) Task 4.8 (the
  verdicts and the measurements)
- Related: [Plan 00237](../Completed/00237-remove-the-dead-handlers/PLAN.md),
  the removal slice of the same audit

## Success Criteria

- [ ] Measured subprocess-spawn and file-read rates fall, verified by the SAME
  method before and after
- [ ] The rendered status line is byte-identical in the steady state
- [ ] Every TTL changed is justified against the measured render interval, not
  chosen as a round number
- [ ] A guard exists that would catch a future TTL drifting back into resonance
- [ ] Full QA passes; daemon restarts RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). The blow-by-blow activity log lives in JOURNAL/. -->

- <!-- milestone or delivery commit hash -->
