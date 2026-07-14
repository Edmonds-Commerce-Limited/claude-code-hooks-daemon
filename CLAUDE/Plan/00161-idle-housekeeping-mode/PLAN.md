# Plan 00161: idle housekeeping mode

**Status**: In Progress
**Created**: 2026-07-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon ships a non-durable hourly **failsafe recovery cron** that fires a
`FAILSAFE RECOVERY CHECK` prompt while the REPL is idle, so work stalled by an
external factor (Claude API overload, rate limit, 5-hour usage limit, network
failure) gets resumed. When there is genuinely nothing to resume, each tick is
a deliberate no-op and the agent simply re-stops. Observed in this very session:
a long run of consecutive no-op ticks, each answered with a near-identical
`STOPPING BECAUSE: ... failsafe tick found nothing to resume`. That idle time is
wasted.

This plan explores turning repeated no-op ticks into a signal: after the session
is demonstrably idle-and-caught-up (clean tree, nothing to resume, N consecutive
no-op ticks), the agent should enter a bounded **housekeeping mode** and spend
the free time on genuinely useful, safe, low-priority maintenance (plan-tree
hygiene, doc/truth drift, QA/coverage health, stale-artifact reaping, etc.)
instead of re-stopping. The mechanism should ideally be daemon-supported — a
handler that detects the repeated-no-op condition and injects ranked
housekeeping guidance — and it must be dogfooded in this repo first.

The critical constraints: housekeeping is strictly LOWER priority than real work
and any genuine recovery; it must yield instantly to a real user prompt; it must
never make risky unattended changes, create noisy/empty commits, fight the Stop
handler, or loop forever burning quota. When housekeeping runs dry it must
genuinely idle-stop.

## Goals

- Characterise the repeated-no-op-tick signal from this session's transcript
  (how many, how identical) and define a robust detection rule with
  false-positive guards.
- Produce a ranked catalogue of housekeeping tasks worth doing in free time,
  each scored by value × autonomy-safety, drawn from this repo but generalisable.
- Sketch a dogfoodable handler design (event type, priority band, terminal flag,
  state persistence for the no-op counter, config options, report-only vs.
  mutate-and-commit boundary).
- Decide an MVP slice small enough to build and dogfood here, then (pending user
  approval of the brainstorm) implement it under TDD.

## Non-Goals

- No autonomous risky changes: housekeeping never force-pushes, deletes user
  work, rewrites history, or makes decisions that are the user's to make.
- Not a heartbeat/pacing mechanism — this must not cause the agent to pace itself
  to the cron or burn quota during genuine idleness.
- Not looping through background agents or other sessions (out of scope, as with
  the supervisor foreground work in Plan 00160).

## Tasks

### Phase 1: Brainstorm & Design (divergent)

- [ ] ⬜ **Task 1.1**: Fable brainstorm agent explores the problem using this
  session's transcript + the repo, writing `BRAINSTORM.md` (detection mechanism,
  ranked housekeeping catalogue, safety guardrails, handler design sketch, open
  questions, MVP slice).
- [ ] ⬜ **Task 1.2**: Review the brainstorm with the user; pick the detection
  rule, the initial task catalogue, and the MVP slice.

### Phase 2: MVP Implementation (TDD) — pending Phase 1 approval

- [ ] ⬜ **Task 2.1**: TDD the no-op-tick detector + housekeeping-guidance
  injection as a handler (RED → GREEN → REFACTOR), report-only first.
- [ ] ⬜ **Task 2.2**: Wire config options (enable/disable, threshold, task
  allowlist, report-only mode); full QA; daemon restart RUNNING; dogfood in-repo.

## Success Criteria

- [ ] A robust detection rule that never trips while the user is waiting, mid-plan,
  or blocked only on human input.
- [ ] A ranked, safety-scored housekeeping task catalogue the user has reviewed.
- [ ] An MVP handler dogfooded in this repo that converts repeated no-op ticks
  into useful, bounded, report-first housekeeping without fighting the Stop
  handler or burning quota.

## Notes & Updates

### 2026-07-14

- Plan scaffolded from a live user request after observing ~15 consecutive
  no-op failsafe recovery ticks in this session.
- Failsafe recovery cron already live for this session: `a8af59d9`
  (`:37` hourly, non-durable). Reused — not duplicated.
- Phase 1 brainstorm delegated to a Fable sub-agent (transcript + repo as
  source); output lands at
  `CLAUDE/Plan/00161-idle-housekeeping-mode/BRAINSTORM.md`.
