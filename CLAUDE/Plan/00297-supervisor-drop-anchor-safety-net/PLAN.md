# Plan 00297: supervisor drop anchor safety net

**Status**: In Progress (implementation complete; hot-reload verification pending)
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

- [x] ✅ **Task 1.1**: The authoritative observed-state source is the
  existing daemon-written context sidecar (`SidecarReading.model_id`/
  `.effort`, Plan 00278 fields) — no new read-back channel was built; a
  separate mechanism reading the SAME source but never trusting the
  injection audit is the fix. `CompactStateMachine._evaluate_anchor()` is
  the `read_session_state()`-equivalent: it consumes every fresh,
  non-stale `SidecarReading` and returns an explicit UNKNOWN (no-op) for a
  `None`/unrecognised effort value rather than guessing either way.
- [x] ✅ **Task 1.2**: Injection verification is READ-BACK ONLY:
  `mark_anchor_injection()` (called by the HOST after a successful PTY
  write) records the attempt but deliberately does NOT clear
  `anchor_active` — only a LATER `_evaluate_anchor()` observing
  `effort == "low"` does. A violation that persists past
  `anchor_injection_due()`'s own cooldown (`_ANCHOR_RETRY_COOLDOWN_SECONDS`,
  25s) is retried; `noop_reason_log`/`reason` name the observed
  `(model_id, effort)` and attempt count on every tick, so a SWALLOWED
  injection is visible in `decision.log` without a separate SWALLOWED enum.

### Phase 2: The anchor

- [x] ✅ **Task 2.1**: `_evaluate_anchor()` runs on every tick via
  `note_model_reading()`; `decide_once()`'s DROP ANCHOR block (checked
  ahead of even the coupled-effort correction) injects `/effort low` gated
  on an empty input box ONLY (never the idle floor), bypasses
  `_EFFORT_REINJECT_COOLDOWN_SECONDS`/`_MAX_EFFORT_INJECTIONS` entirely via
  its own `anchor_injection_due()` cooldown, and is never permanently
  deferred by a busy input box — it stays `anchor_active` and retries on
  the next unobstructed tick.
- [x] ✅ **Task 2.2**: `anchor_escalated_at()` flips true after
  `_ANCHOR_MAX_ATTEMPTS` (3) unverified attempts or
  `_ANCHOR_ESCALATION_BOUND_SECONDS` (300s), whichever comes first;
  `supervise()`'s `_on_poll` posts a rate-limited, warning-level
  owner-facing alert (`_ANCHOR_ALERT_TEXT`) via the existing
  `StatusMessagePoster` channel while escalated. The anchor block also
  preempts a `WOULD_CONTINUE` nudge (replacing it with the `/effort low`
  correction) and the goal-signal block is naturally starved (it only ever
  fires on an otherwise-NOOP tick, which an active anchor never leaves).
  **Deviation from the brief**: an ESC interrupt was NOT added — compact/
  escape decisions (`WOULD_COMPACT`/`WOULD_ESCAPE`) are left untouched
  because they manage an in-flight compaction rather than invite more
  work, and interrupting mid-compaction risked a worse outcome than the
  effort correction it would have protected. See the JOURNAL for the
  full rationale.
- [x] ✅ **Task 2.3**: `_coupled_effort_target()` now clamps the top-ranked
  family's configured floor to `_ANCHOR_TARGET_EFFORT` ("low") whenever it
  would resolve above that ceiling (covers a `CCY_MIN_EFFORT_LEVELS`
  misconfiguration carrying an Opus-era floor onto Fable) — but the DROP
  ANCHOR invariant itself is the real model-awareness guarantee: it
  re-evaluates on every observed `/model` change via `note_model_reading`,
  independent of the raise-only floor logic entirely, so no path can leave
  fable above low uncorrected for more than one anchor retry cycle.

### Phase 3: Verification and rollout

- [x] ✅ **Task 3.1**: `test_swallowed_anchor_injection_retries_after_its_own_cooldown`
  reproduces the 16:01:35 scenario (fable observed at xhigh persists across
  a "swallowed" tick where the sidecar never catches up) and proves the
  anchor retries after its own cooldown, not the floor mechanism's.
  Worker hot-reload verification is explicitly OUT OF SCOPE for this
  implementing agent per its task brief ("that's the coordinator's job
  afterwards") — not performed here.
- [x] ✅ **Task 3.2**: Documented via the extensive in-code rationale on
  the new constants/methods (the project's established pattern for this
  file — see the existing Plan 00278/00281 sections it follows) and this
  PLAN.md/JOURNAL. No separate prose doc was added; `.claude/ccy/CLAUDE.md`
  needs no change (the hot-reload contract is unaffected).

## Success Criteria

- [x] A simulated swallowed `/effort low` injection while on Fable is
  detected by read-back and corrected without owner intervention.
- [ ] When correction is impossible (injections keep being swallowed), the
  supervisor halts work-continuing injections and interrupts the session
  within the bound — Fable never runs another turn above low effort.
  **Partial**: continue/goal nudges ARE suppressed and a loud owner alert
  IS posted, but the ESC interrupt was deliberately not implemented (see
  Task 2.2 deviation in the JOURNAL) — still open.
- [x] A `/model` flip to Fable while an xhigh effort floor is active results
  in observed effort low, verified by read-back, not by the audit log.
- [x] Anchor events appear in the decision log with observed-state evidence
  (model_id + effort + attempt count in every `reason`/`noop_reason_log`).

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
