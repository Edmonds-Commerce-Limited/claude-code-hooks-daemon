# Plan 00318: supervisor audit via status line banner

**Status**: In Progress
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Fable
**Execution Strategy**: Direct (main session, dogfooded live)

## Overview

The ccy supervisor announces the silent actions it took on the user's behalf
(`/model`, `/effort`, flag-cleaning `/compact`) by INJECTING a chat line into
the session: `🧾 🤖 [ccy-supervisor …] audit — silent supervisor actions on your behalf: …`. That costs a whole model turn, lands in the transcript
forever, and consumes context — a heavy price for a notice whose only real
audience is the human watching the terminal.

Plan 00312's Ctrl+C interception proved the alternative works: a transient
status-line banner, posted through the supervisor's own
`StatusMessagePoster` → `supervise/status-message.json` channel, rendered by
the daemon's `supervisor_indicator` handler and auto-omitted on expiry. The
owner's verdict after living with it: *"I've seen the ctrl c status line
banner which works really well — I think we should just use that for this
supervisor actions notification."*

This plan moves the audit trail onto that channel with a longer TTL (~30s, vs
the 10s default sized for a keystroke hint) and a visible countdown, so the
user can see the notice is transient rather than wondering whether it is
stuck. `decision.log` remains the durable audit record; the banner is the
glance-able surface.

## Goals

- The audit trail surfaces as a transient status-line banner, not an injected
  chat line — zero model turns, zero transcript/context cost.
- Audit banners live ~30 seconds (independent of the existing 10s default for
  keystroke hints) and render a visible countdown of the seconds remaining.
- The countdown is opt-in per message, so the Ctrl+C banner (whose own text
  already names a 3s confirm window) is not confused by a second number.
- `decision.log` stays the durable, complete audit record.

## Non-Goals

- Changing WHICH actions are audited, or the wording of the audit items.
- Removing the injection mechanism for other families (`/compact`, `/goal`,
  standing-auth reinforcement) — those are real instructions to the session,
  not notices to the human.
- Retro-fitting a countdown onto the Ctrl+Z / Ctrl+\\ / Ctrl+C notices.

## Tasks

### Phase 1: countdown-capable status message channel

- [ ] ⬜ **Task 1.1**: Add an opt-in `countdown` flag to the on-disk status
  message payload (supervisor writer side: `write_status_message` /
  `StatusMessagePoster.post`, with a per-post TTL override).
- [ ] ⬜ **Task 1.2**: Render the countdown in `supervisor_indicator` —
  `(Ns)` appended to the message text, computed from `expires_at` minus
  the wall clock, only when the payload sets `countdown`. Clamp at 0 and
  keep the existing fail-silent behaviour for malformed payloads.

### Phase 2: audit trail moves to the banner

- [ ] ⬜ **Task 2.1**: Post the audit summary to the status-line channel
  instead of returning it as an injectable payload; keep the pending-item
  bookkeeping (`arm_audit` / `mark_audit_injection`) and the decision.log
  line.
- [ ] ⬜ **Task 2.2**: Compose a SHORT banner form of the audit text (the
  status line is width-constrained — the chat form's provenance preamble
  and log path do not fit and are not needed on a banner).
- [ ] ⬜ **Task 2.3**: Drop the `can_inject` gate for the audit family — a
  banner needs neither an idle session nor an empty input box, so the
  notice can surface immediately.

### Phase 3: dogfood live

- [ ] ⬜ **Task 3.1**: Hot-reload the worker, provoke a real supervisor action
  (a `/model` switch re-applies its coupled effort), and confirm the
  banner appears with a counting-down TTL and no injected chat line.

## Success Criteria

- [ ] A supervisor action produces a status-line banner and NO chat injection.
- [ ] The banner shows a decreasing seconds countdown and disappears on expiry.
- [ ] The Ctrl+C / Ctrl+Z banners are unchanged (no countdown suffix).
- [ ] `decision.log` still records every audited action.
- [ ] QA green; live evidence recorded in `JOURNAL/`.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
