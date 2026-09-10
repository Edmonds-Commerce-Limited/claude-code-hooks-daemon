# Plan 00366: supervisor own line follow up

**Status**: Complete
**Created**: 2026-09-10
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

Field incident, this repository's own supervised session. At 22:52 the
armed supervisor pasted a `/goal` line into the input box while the agent
was mid-turn, pressed Enter, and logged the injection as done. The Enter did
not submit the line. Nothing the supervisor tracks could tell it so: its own
injections are deliberately kept out of the input-box model (so a human's
half-typed line is never typed over), and it never confirms that a submitted
line became a prompt. The line sat in the box until the owner pressed Enter
by hand at 06:40 the next morning. `decision.log` showed a normal injection
line and then eight hours of silence.

The owner's ruling: when the supervisor reasons about text in the box, it
must recognise its OWN text. This plan makes a submitted injection a
remembered own line, follows it up with an Enter at the next lull, and stops
the subordinate families typing more text on top of it. It also replaces the
lifetime goal cap, which the same long-lived session had already exhausted
(five goals over a thirteen-hour session), with a rolling one-hour budget.

## Goals

- A submitted injection is remembered as the supervisor's own unconfirmed
  line, visible in the machine state and `decision.log`.
- At the next lull (human idle, box empty of human text, child quiet) the
  supervisor presses Enter for it, bounded to two attempts, and logs why.
- A human Enter, or the session going busy after a follow-up Enter, clears
  the record without a keystroke; a spent budget clears it with a log line.
- Goal, goal-clear and standing-auth injections defer while an own line is
  pending, naming the reason.
- The goal cap counts injections inside a rolling window, not per process
  lifetime.

## Non-Goals

- No host-side change: the fix ships by worker hot-reload alone, so the live
  session is protected without a restart.
- No attempt to read the input box back from the child's output stream.

## Tasks

### Phase 1: TDD fix

- [x] ✅ **Task 1.1**: Failing tests for the own-line record, the follow-up
  Enter and its gates, the clearing rules, the text-family deferral, the
  worker-side human-Enter edge and the rolling goal cap
  (`tests/unit/supervise/test_own_line_resubmit.py`).
- [x] ✅ **Task 1.2**: Implement in `.claude/ccy/claude-supervise.py`:
  `HumanInputLine.take_enter_pressed`, `TickFacts.human_enter_pressed`, the
  own-line fields and methods on `CompactStateMachine`, the follow-up block
  in `decide_once` ahead of the goal family, and
  `goal_injections_within` with `_GOAL_CAP_WINDOW_SECONDS`.
- [x] ✅ **Task 1.3**: Supervisor suite green; worker reload verified by pid
  (a new worker after the edit); release-notes callout 17.

## Success Criteria

- [x] A `/goal` left unsubmitted mid-turn is submitted by the supervisor at
  the next lull, and the log says so.
- [x] The subordinate families never paste on top of a pending own line.
- [x] A thirteen-hour session can still receive a sixth goal.
- [x] Every release-bound consequence is in the pending-release holding
  area: `UNRELEASED/release-notes/17-the-supervisor-follows-up-its-own-unsubmitted-line.md`

## Delivery & Milestones

- The fix, tests and callout land in one commit; archived in the same
  commit, being a single-sitting incident fix.
