# Plan 00508: operator signal reaches a busy agent

**Status**: In Progress
**Created**: 2026-10-12
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #77

## Overview

`hooks-daemon signal` writes a per-session `.operator-signal` file. The signal
is a reboot warning, a shutdown warning, or a reboot-cancelled notice; the
format and writer are in `utils/operator_signal.py`, and the design is from Plan
00417\. The ccy supervisor types the rendered warning into the session only when
the session is idle with an empty input box. While a turn runs, the supervisor
shows the warning on the status line and defers it.

So an agent in a long turn is not told until the turn ends, and that can be
after the stated minutes have run out. The status line reaches a human, not the
agent. The issue's own hypothesis is refuted: there is no queued line for an
Escape to flush, because nothing is typed into a busy session. Triage is in the
#77 comments.

Coordinator ruling, a clear winner: the daemon delivers the warning at the next
tool boundary. When a hook event fires for a session that has a pending,
unexpired operator signal, a PostToolUse handler adds the signal's rendered
text as `additionalContext`. It does this once per signal, keyed on the
signal's identity: session, `ts` and kind.

- The handler never deletes, consumes or rewrites the signal file. The
  supervisor's idle-time injection is unchanged and remains the only consumer.
- Pressing Escape mid-turn is not adopted, because it cancels in-flight work.

## Goals

- A busy agent sees a pending reboot or shutdown warning within one tool call,
  with the minutes it states.
- A reboot-cancelled notice is surfaced the same way.
- Each signal is surfaced once per session.
- A malformed, expired or other-session signal is ignored, and the reason is
  logged.

## Non-Goals

- Changing the supervisor or its idle-time injection.
- Interrupting a running turn.

## Tasks

### Phase 1: Fix

- [ ] ⬜ **Task 1.1**: RED. Tests for the new handler cover:
  - the handler's own session's signal is surfaced, with the text and minutes;
  - a second event for the same signal is silent;
  - a newer signal is surfaced again;
  - another session's signal, an expired signal and a malformed file are each
    ignored (logged), and the handler never raises;
  - the signal file is left in place.
- [ ] ⬜ **Task 1.2**: GREEN. Implement the handler.
  - Reuse the existing renderer and validation, so the text matches what the
    supervisor would type. Where that code lives only in the supervisor, put
    the shared part in `utils/operator_signal.py`. Do not import the
    supervisor.
  - Register the handler in the config template and the dogfood config,
    enabled by default.
  - Add `get_claude_md` guidance, a HANDLER_REFERENCE entry and acceptance
    tests.
- [ ] ⬜ **Task 1.3**: Add a release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

### Phase 2: Land

- [ ] ⬜ **Task 2.1**: Review, coordinator checks and merge; then comment on
  and close #77.

## Success Criteria

- [ ] A pending operator signal reaches the agent mid-turn as hook context,
  once.
- [ ] The supervisor's idle-time injection and its consumption of the signal
  are unchanged.
- [ ] The release-bound consequence, a new default-enabled handler, is in the
  pending-release holding area as a release note.

## Delivery & Milestones

- Issue #77 triaged and claimed.
