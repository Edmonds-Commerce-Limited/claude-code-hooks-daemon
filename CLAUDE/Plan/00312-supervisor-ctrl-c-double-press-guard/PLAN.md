# Plan 00312: supervisor ctrl c double press guard

**Status**: Not Started
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner field report: in current Claude Code, Ctrl+C is wired to kill
background agents. A single accidental `^C` — muscle memory from any other
terminal — can destroy hours of delegated background work. The owner asks
whether the first `^C` can be intercepted while "spamming" Ctrl+C still
gets through (the escape hatch must remain absolute).

The ccy supervisor is the right interception point and makes this cheap:
`claude-supervise.py` already owns the PTY between the terminal and the
`claude` process, and every keystroke — including the raw 0x03 byte — flows
through its `_forward_io` loop. No terminal reconfiguration, no signal
trickery in Claude Code itself: the supervisor simply declines to forward a
lone 0x03 and forwards it when a second arrives inside the confirm window.

Danger acknowledged and designed around: `^C` is also the legitimate way to
interrupt a runaway turn, so the guard must never make interruption
impossible — the second press ALWAYS forwards, the swallowed first press is
loudly visible, and the guard is configurable/disable-able.

## Goals

- A single `^C` does not reach the `claude` child; the supervisor renders a
  visible hint ("^C intercepted — press Ctrl+C again within Ns to
  interrupt") without disturbing the TUI more than necessary.
- A second `^C` within the confirm window is forwarded immediately
  (spamming always wins — two rapid presses behave like today).
- The guard is a supervisor config option (window seconds; enabled flag),
  on by default in this repo for dogfood, with the decision log recording
  every swallow and every forward.

## Non-Goals

- Changing Claude Code's own Ctrl+C semantics (upstream; out of reach).
- Intercepting any other control byte (^Z, ^D untouched).
- Protecting non-supervised sessions (no supervisor = no guard; document).

## Open Questions (settle in Phase 1)

- Paste-burst safety: 0x03 arriving inside a bracketed-paste or multi-byte
  burst must not be treated as a press (inspect surrounding bytes/timing).
- Whether the hint can be rendered without corrupting the child TUI (the
  supervisor already injects marker lines; reuse that mechanism), and
  whether the hint belongs on the supervisor's own status surface instead.
- Interaction with the supervisor's own ESC injection (Plan 00297 anchor
  escalation) — ordering and cooldowns must not deadlock an interrupt.
- Whether terminals send anything other than a single 0x03 for Ctrl+C
  variants (verify real byte sequences in the live ccy PTY).

## Tasks

### Phase 1: Design spike and byte-level verification

- [ ] ⬜ **Task 1.1**: In a live supervised PTY, capture what actually
  arrives on Ctrl+C (single byte 0x03? repeats on hold?), on paste bursts
  containing 0x03, and confirm the child's observable behaviour when 0x03
  is withheld. Record findings + the settled design (window length default,
  hint rendering route) in a supporting doc.

### Phase 2: Implement in the supervisor (TDD)

- [ ] ⬜ **Task 2.1**: Implement the double-press gate in `_forward_io`'s
  stdin path: swallow the first 0x03, arm a timestamp, forward on a second
  within the window; expire the arm after the window. Config plumbing +
  decision-log entries. Unit tests for: single press swallowed, double
  press forwarded, window expiry re-arms, paste-burst exemption,
  disabled-flag passthrough.
- [ ] ⬜ **Task 2.2**: Hot-reload/live verification per the supervisor
  contract (verify the worker pid changed post-edit before testing), then
  live dogfood: single ^C shows the hint and kills nothing; double ^C
  interrupts as before. Journal the live evidence.

## Success Criteria

- [ ] An accidental single ^C in a supervised session kills no background
  agents and visibly explains itself.
- [ ] Two rapid ^C presses interrupt exactly as today (verified live).
- [ ] Guard is configurable and its actions appear in the decision log.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00312-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
