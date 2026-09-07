# Plan 00342: prose guard does not reach stop handlers

**Status**: Not Started
**Created**: 2026-09-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

Plan 00228 named a recurring defect: a handler that matches its own trigger
vocabulary anywhere in a text fires on prose *about* the trigger. It shipped
`tests/integration/test_handlers_do_not_match_prose.py` as the guard, and that
guard found the real `pipe_blocker` quoted-heredoc bug on its first run.

The guard covers **PreToolUse handlers only**, and says so in its own
docstring: its fixture is a Bash tool call, so handing that payload to a Stop
handler "asks it a question about an event it never receives". That was a
sound decision when no Stop handler had trigger vocabulary. It no longer holds.

`AutoContinueStopHandler` now matches text to decide whether to arm cron
suppression — the `[awaiting-human]` token (Plan 00337 Phase 3) and the four
`_HUMAN_BLOCKED_PATTERNS` phrases (Plan 00298, widened by Plan 00314). The
token half already produced the bug once, in the same session it was written:
a stop message reporting the feature armed suppression on a session that was
not blocked. That was caught by hand and fixed by anchoring the token to the
declaration position. Nothing would have caught it automatically, and nothing
catches the identical weakness in the prose patterns today.

The failure mode is what makes this worth a plan rather than a shrug. A prose
false-positive in a PreToolUse handler produces a wrong DENY — loud, visible,
immediately obvious. Here it produces **silence**: cron ticks stop arriving,
the session loses its recovery net, and there is no error anywhere.

## Evidence

- The scope limit is explicit, in `_in_scope_handlers()`'s own docstring:
  "Restricted to the PreToolUse package because the fixture is a Bash tool
  call... an early draft of this guard did exactly that and reported every
  Bash fixture as a failure of `AutoContinueStopHandler`."
- The token bug, reproduced and fixed under Plan 00337 Phase 3: a stop reading
  `STOPPING BECAUSE: Phase 3 is shipped — the [awaiting-human] token now arms the marker` armed cron suppression. Now pinned by
  `test_merely_discussing_the_token_does_not_arm_it`.
- The prose patterns still have it. A stop message quoting `blocked only on human input` — for instance while explaining this very subsystem — arms the
  marker. That is Plan 00298 behaviour, not a regression, and it has never
  been tested either way.
- Dedupe scout checked 45 live plans: nothing covers extending the guard's
  scope, and nothing covers the prose patterns matching quoted text.

## Goals

- A Stop handler's text matching is covered by the same guard that covers
  PreToolUse handlers, rather than by whoever happens to notice.
- The `_HUMAN_BLOCKED_PATTERNS` phrases stop arming on prose that merely
  quotes them.
- The guard's scope is a stated decision, not a side effect of which fixture
  shape it was first written with.

## Non-Goals

- Re-opening `_HUMAN_BLOCKED_PATTERNS` for widening. Plan 00337 Task 3.4
  closed the set to extension; this plan narrows what they match, never adds.
- Extending the guard to every remaining event type. Stop is the one with
  demonstrated trigger vocabulary; a general sweep is a different job and
  would need a fixture per event.
- Changing the `[awaiting-human]` token's anchoring. That is already fixed and
  pinned; this plan makes the class of bug detectable, not that instance.

## Tasks

### Phase 1: Extend the guard to Stop

- [ ] ⬜ **Task 1.1**: Give the guard a Stop-shaped fixture. The existing one
  is a Bash `tool_input`; a Stop handler needs a transcript path whose last
  assistant message contains the non-executing text. The existing tests in
  `tests/unit/handlers/stop/test_auto_continue_stop.py` already build exactly
  that shape — reuse it rather than inventing a second transcript builder.
- [ ] ⬜ **Task 1.2**: Decide how a handler declares which fixture shape
  applies to it. Today `_in_scope_handlers()` filters by module path, which is
  a proxy for "takes a Bash tool call". With two shapes that proxy stops
  working and needs replacing with something explicit.
- [ ] ⬜ **Task 1.3**: Keep the non-vacuity guards honest.
  `TestTheGuardIsNotVacuous` exists because an earlier version passed while
  checking nothing; whatever scoping Task 1.2 chooses needs the same
  protection, per fixture shape.

### Phase 2: Narrow the prose patterns

- [ ] ⬜ **Task 2.1**: Establish the intended rule first. The token was fixed
  by anchoring to the declaration position; the same answer may not fit the
  prose patterns, which were deliberately written to match natural phrasing
  anywhere in a stop reason. Anchoring them could regress wordings that work
  today, which the Plan 00337 Non-Goals forbid.
- [ ] ⬜ **Task 2.2**: Whatever rule Task 2.1 lands on, pin it with a test
  whose fixture is a stop message *discussing* the mechanism — the real shape,
  taken from this repository's own history, not an invented one.
- [ ] ⬜ **Task 2.3**: If the answer is "cannot be narrowed without
  regressing", record that and close the phase. The token exists precisely so
  the patterns can stay frozen; concluding they must also stay imprecise is a
  legitimate result, provided it is written down rather than left implicit.

## Success Criteria

- [ ] A Stop handler that matches its own trigger vocabulary in prose is
  reported by the prose guard, with the same clarity as a PreToolUse one.
- [ ] The guard's scope is stated as a decision, and its non-vacuity tests
  cover every fixture shape it carries.
- [ ] The prose-pattern question has an answer with a test behind it, or a
  recorded reason why it cannot be narrowed.
- [ ] Full QA green (25/25) and the daemon restarted and verified before the
  terminal status flip.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00342-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: Plan 00337 Phase 3, which hit this bug in its own implementation and
  fixed the instance while explicitly leaving the class to a follow-up.
- Prior art: Plan 00228 built the guard and chose its PreToolUse scope for a
  good reason that has since expired.
