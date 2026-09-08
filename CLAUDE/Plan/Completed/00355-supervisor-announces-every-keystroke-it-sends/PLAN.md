# Plan 00355: supervisor announces every keystroke it sends

**Status**: Complete
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

The owner reported the supervisor "might be sending in random esc presses". It
is sending them, and they are not random — but from the other side of the
terminal there is no way to tell the difference, which is the actual defect.

Measured in this session's `decision.log`: **122 `would-escape` injections**,
every one of them the same path — `queued /compact stalled -> would inject [esc] to flush` — and every one at attempt **1/5**, never 2/5. So the ESC is
both legitimate and effective: one press unsticks the queued compaction and the
counter resets. Against 163 `would-compact` decisions, roughly three in four
queued compactions need that nudge, which is why the owner notices them.

What they lack is any notice. Plan 00318 built a transient status-line audit
banner precisely so a silent injection is visible, but `arm_audit()` is called
from three places only — `/effort`, `/model` and `/compact`. `WOULD_ESCAPE` and
`WOULD_RESUBMIT` inject a raw keystroke and arm nothing, so the one family with
**no chat trace at all** is also the one family that never announces itself.

## Goals

- Every keystroke the supervisor injects raises the status-line banner, with the
  countdown, at the time it is sent.
- The banner reads as a comma-separated tally when actions stack up —
  `esc (20), compact (15)` — instead of a truncated semicolon list.
- `decision.log` remains the durable record; the banner stays a convenience
  surface that can be lost without losing the audit.

## Non-Goals

- **Not** reducing the number of escapes. They are the mechanism that unsticks a
  stalled compaction, they work on the first attempt, and making them rarer is a
  separate question from making them visible. If the stall rate itself is worth
  attacking, that is its own plan with its own measurement.

- **Not** moving the banner onto `StatusMessagePoster`'s lock and rate limit.
  Plan 00319 Task 3.2 (F9) already tracks that the audit banner writes the status
  message directly, bypassing both. This plan increases how often that write
  happens, so it makes F9 more relevant — but fixing it here would fold two
  independent changes into one.

  **Since shipped, under 00319 rather than here** — and the separation paid off:
  moving onto the poster turned out to be impossible (its lock is process-local
  and the two writers are in different processes), so F9 needed a different
  mechanism entirely. Folding it in would have buried that finding inside this
  plan's diff. See 00319 Task 3.2.

- **Not** announcing anything the supervisor did not do. A dry-run marker is not
  a keystroke and must not be tallied as one.

## Context & Background

| Plan  | Title                                   | Status      | Relevance                                                       |
| ----- | --------------------------------------- | ----------- | --------------------------------------------------------------- |
| 00318 | Supervisor audit via status line banner | Complete    | Built the banner and `arm_audit`; this extends its coverage     |
| 00319 | Supervisor release review followups     | Not Started | Task 3.2 (F9): the banner bypasses the poster's lock/rate limit |
| 00297 | DROP ANCHOR escalation                  | Complete    | Owns the second ESC path (`is_anchor_escape`), also unannounced |
| 00164 | Two-tier host/worker split              | Complete    | `arm_audit` is worker-side, so this ships by hot-reload         |

A dedupe scout checked all 42 live plans and found no other coverage.

**The flush condition is the interesting constraint.** The existing banner
flushes only on a tick that is `NOOP`, in `MONITOR`, with no signal pending —
deliberately, so a `/model` + coupled `/effort` sequence surfaces as ONE banner
once the sequence is complete. An ESC fires in `AWAIT_COMPACTING`, so an
escape armed under today's rules would surface minutes later, in a state that
has nothing to do with it, or not at all. Timely is the whole point of this
plan, so the flush rule has to change — without losing 00318's batching for the
slash-command families, whose sequence genuinely is meaningful.

## Tasks

### Phase 1: Decide the shape

- [x] ✅ **Task 1.1**: What the parenthesised number means.

  **Decided: a per-action COUNT.** The owner's `esc (20), compact (15)` sits
  next to "where they stack up", and a stack is a quantity. The rejected
  reading was a per-item countdown: the banner already carries exactly one
  countdown — its own 30s TTL, built by 00318 — so a second, per-item countdown
  would be two different clocks on one line with nothing to distinguish them.

  Two consequences follow from choosing a tally:

  - A count renders only when it is >1. `esc (1)` is noise; the bare name
    already says it happened once.
  - `_AUDIT_BANNER_MAX_ITEMS` and its `+N more` truncation are **deleted**, not
    kept. They existed to bound a list that could not bound itself; a tally is
    bounded by the number of DISTINCT actions, which is small. Truncation would
    now hide information for no gain.

  The label is the command text with the leading slash stripped, so a command
  and a key read alike (`compact`, `effort low`, `esc`). The ARGUMENT stays:
  `effort low` and `effort high` are different actions, and tallying them
  together would report a number nobody can act on.

- [x] ✅ **Task 1.2**: When a keystroke banner flushes.

  **Decided: flush on the tick that sends the key** — the third condition, not
  a replacement for the existing one. Both rules now coexist: the slash-command
  families keep 00318's "NOOP, in MONITOR, nothing pending" batching, and a
  keystroke additionally flushes immediately.

  - *Flush on any injection tick* — rejected. It collapses 00318's batching, so
    a `/model` + coupled `/effort` sequence would emit two banners mid-sequence
    instead of one at the end.
  - *Time-windowed rolling tally* — rejected as scope. It would let a stack
    accumulate before being shown, which sounds closer to `esc (20)`, but it
    delays the notice by design and this plan's whole complaint is that the
    escapes are invisible when they happen. A stack still forms naturally
    whenever escapes land inside one banner's TTL.

  **The subtlety that made this non-obvious**: the flush block composes its own
  `reason` string, and `reason` is what reaches `decision.log`. Reusing the
  block wholesale on a keystroke tick overwrites `queued /compact stalled -> would inject [esc]` with `audit trail flush (1 item(s))` — destroying the
  exact log line that made these 122 escapes diagnosable. So a keystroke tick
  keeps its own `decision_value`, `reason` and `noop_reason_log`; only the
  banner write and the pending-clear are shared. Pinned by
  `test_the_escape_keeps_its_own_reason_in_the_decision_log`.

  Arming is keyed on the decision VALUE rather than done at each injection
  site, so the DROP ANCHOR escalation — which reaches the escape path by
  assigning `decision_value` directly, after `_resolve_payload` has run — is
  covered by the same rule instead of needing its own call that a later branch
  could forget.

### Phase 2: Build it

- [x] ✅ **Task 2.1**: RED — tests in `tests/unit/supervise/test_audit_banner.py`
  for: an ESC arms an audit item; a dry-run marker does NOT; the banner renders
  a comma-separated tally; a count appears only when an action stacks; the
  banner still carries its countdown.

- [x] ✅ **Task 2.2**: GREEN — `_KEYSTROKE_AUDIT_LABELS`, `_audit_action_label`,
  and `_format_audit_banner` reshaped into a tally.

- [x] ✅ **Task 2.3**: The flush rule from Task 1.2. `test_a_slash_command_still_waits_for_its_sequence_to_finish`
  pins 00318's batching so it cannot regress unnoticed.

### Phase 3: Verify

- [x] ✅ **Task 3.1**: Full QA green (26/26, 19962 passed, coverage 95.2%),
  daemon restart RUNNING.

- [x] ✅ **Task 3.2**: **The WORKER reload is verified, not assumed.** The host
  is pid 2 (started Sep 4, owning the live `claude` process); the worker is its
  child, and it respawned at `10:09:39` — five seconds after the file's last
  write at `10:09:34`, matching the ~5s `_WORKER_RELOAD_CHECK_SECONDS` poll.
  The live worker is therefore running this code, and no session restart was
  needed. Recorded here because the trap it avoids is silent: a `git log` time
  is not a deploy time, and testing against a stale worker "verifies" the old
  code.

- [x] ✅ **Task 3.3**: Observed on a natural occurrence, not forced: the
  `decision.log` line `would-escape: queued /compact stalled -> would inject [esc] to flush (1/5); injected '\x1b'` was followed on the same tick by the
  banner file `{"text": "🧾 ⌨️ esc", "level": "info", "countdown": true}`,
  with an expiry one TTL after the injection.

## Success Criteria

- [x] An injected ESC produces a visible status-line banner naming it
- [x] A stack of actions renders as `esc (N), compact (M)`, comma-separated
- [x] A `/model` + coupled `/effort` sequence still surfaces as ONE banner
- [x] `decision.log` still records every injection regardless of banner outcome
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/04-supervisor-announces-every-keystroke.md`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00355-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed from an owner report, with the 122 escapes measured from
  `decision.log` rather than inferred.
- Shipped at `e105530e` (keystroke banner + tally), with the flush-reason
  regression and the INFO-yields-to-WARNING precedence in the follow-on
  supervisor commits; closed on the first natural post-reload ESC.
