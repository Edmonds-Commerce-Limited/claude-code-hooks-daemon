# Plan 00297: supervisor drop anchor safety net

**Status**: Not Started
**Created**: 2026-08-31
**Owner**: joseph
**Priority**: Critical
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

On 2026-08-31 the session ran the Fable model at XHIGH effort for roughly an
hour, burning a large share of the account's weekly Fable allowance. The chain:
at 15:19:43 the supervisor's effort floor injected `/effort xhigh` while the
session was on Opus; at 16:01:32 the model was flipped to Fable; at 16:01:35
the supervisor injected `/effort low` but the injection was **swallowed** by a
busy session (and a follow-up at 16:04:55 was deferred: "input box not empty").
The supervisor's audit recorded the injection as done, so from its point of
view the session was at low effort — while the real session ran Fable at XHIGH
until the owner noticed and set `/effort low` by hand.

The defect class is **inject-and-assume**: the supervisor mutates session
state through the PTY and trusts its own audit log, with no read-back of the
session's actual state. A swallowed injection is therefore invisible, and the
most expensive misconfiguration the product allows (Fable above low effort)
persists silently. Fable at XHIGH can wipe out a weekly allowance in minutes,
so this combination must be treated as an emergency, not a preference.

This plan builds a **DROP ANCHOR** safety net into the ccy supervisor: a
continuously-verified invariant — `model == fable` implies `effort == low` —
checked against **observed** session state (read back from the session, never
from the injection audit), with an escalating response that ends in stopping
all work rather than letting the session keep burning.

## Goals

- **Read-back verification as a primitive**: the supervisor can determine the
  session's ACTUAL current model and effort level from the session itself
  (statusline / transcript / session state file), never by replaying its own
  injection history. Every injection of `/effort` or `/model` is verified by
  read-back within a bounded window, and a swallowed injection is detected and
  retried.
- **The DROP ANCHOR invariant**: whenever observed state is Fable at any
  effort above low, the supervisor enters an emergency mode — inject
  `/effort low`, verify by read-back, retry aggressively, and if the state
  still cannot be corrected within a short bound, STOP EVERYTHING: interrupt
  the session (send ESC / halt injections that would prompt more work) and
  alert the owner loudly rather than allowing another turn at XHIGH.
- **Effort-floor rules become model-aware**: the floor that injected
  `/effort xhigh` for Opus must never survive a model flip to Fable — a model
  change re-evaluates the effort policy immediately.
- **Every anchor event is durably logged** in the supervisor decision log with
  observed-state evidence, so a post-incident review never has to reconstruct
  what the session was really running.

## Non-Goals

- Changing which models or effort levels the owner may choose manually — the
  net constrains what the SUPERVISOR allows to persist, and Fable-above-low is
  anchored because the owner ruled it; it does not second-guess other choices.
- General allowance/spend accounting or quota tracking — this is a state
  invariant, not a billing monitor.
- Restarting the ccy session or the PTY child as a remedy (the two-tier
  design exists to avoid that); the anchor works through injection,
  interruption and alerting only.
- Fixing every swallowed-injection case for every command — `/goal`,
  `/compact` etc. keep current behaviour; read-back verification is built for
  `/model` and `/effort` first because that is where the money is.

## Tasks

### Phase 1: Observed-state read-back

- [ ] ⬜ **Task 1.1**: Identify the authoritative on-disk/observable source
  for the live session's current model and effort (session state file,
  transcript tail, or statusline input), and TDD a `read_session_state()`
  helper in `.claude/ccy/claude-supervise.py` that returns
  `(model, effort, observed_at)` or an explicit UNKNOWN — never a guess.
- [ ] ⬜ **Task 1.2**: TDD injection verification: after injecting `/effort`
  or `/model`, the worker schedules a read-back check; if observed state does
  not reflect the injection within the bound, the injection is marked
  SWALLOWED in the decision log and retried when the session is quiet.

### Phase 2: The anchor

- [ ] ⬜ **Task 2.1**: TDD the DROP ANCHOR invariant check on every worker
  tick: observed `model == fable && effort != low` → emergency mode. Emergency
  mode injects `/effort low` with retry-until-verified semantics that bypass
  the normal "input box not empty" deferral backoff.
- [ ] ⬜ **Task 2.2**: TDD the stop-everything escalation: if the invariant
  cannot be restored within the bound, the supervisor interrupts the session
  (ESC injection) instead of letting another turn run, suppresses all
  work-continuing injections (`continue`, goal nudges) while anchored, and
  writes a loud owner-facing alert.
- [ ] ⬜ **Task 2.3**: Make the effort-floor rule model-aware: a `/model`
  change (observed, not just injected) immediately re-evaluates effort policy,
  so an Opus-era xhigh floor can never carry over onto Fable.

### Phase 3: Verification and rollout

- [ ] ⬜ **Task 3.1**: Reproduce the 16:01:35 swallowed-injection scenario in
  a test (busy session swallows `/effort low` after a model flip) and prove
  the anchor detects and corrects it, then verify the worker hot-reload per
  the supervisor contract (ps pid check, kill worker if stale).
- [ ] ⬜ **Task 3.2**: Document the anchor in the supervisor docs and the
  decision-log format; record the incident evidence pointers in this plan's
  JOURNAL.

## Success Criteria

- [ ] A simulated swallowed `/effort low` injection while on Fable is
  detected by read-back and corrected without owner intervention.
- [ ] When correction is impossible (injections keep being swallowed), the
  supervisor halts work-continuing injections and interrupts the session
  within the bound — Fable never runs another turn above low effort.
- [ ] A `/model` flip to Fable while an xhigh effort floor is active results
  in observed effort low, verified by read-back, not by the audit log.
- [ ] Anchor events appear in the decision log with observed-state evidence.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
