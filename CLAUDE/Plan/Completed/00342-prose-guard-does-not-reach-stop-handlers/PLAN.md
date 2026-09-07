# Plan 00342: prose guard does not reach stop handlers

**Status**: Complete
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

- [x] ✅ **Task 1.1**: **Shipped**, reusing the existing transcript shape
  rather than a second builder.

  **`_denies()` is the wrong predicate on this axis, and a straight copy of
  the guard would have passed vacuously.** On PreToolUse the failure is a
  wrong DENY. On Stop the handler writes the marker and then returns its
  NORMAL decision, so a decision-shaped guard reports a clean pass on a
  handler that has just silently disarmed the session's recovery cron. The new
  `_arms_suppression()` predicate observes the SIDE EFFECT — the marker file
  on disk, against a redirected untracked dir — because that is the
  consequence, and the consequence is what the guard is for.

- [x] ✅ **Task 1.2**: **Scope by BASE CLASS, not module path.** Every handler
  already inherits from exactly one event base, and that inheritance IS the
  declaration of which payload it receives. `issubclass` is explicit, cannot
  drift from the directory layout, and — the property that decided it —
  requires nothing to be added to a NEW handler for it to be covered, which is
  the default-in-scope property the guard is built on (Plan 00228 Decision 1).

  A `fixture_shape = "bash"` class attribute was the obvious alternative and is
  worse on exactly that axis: a second source of truth for something the base
  class already states, and it fails OPEN — a handler that omits it silently
  leaves the guard.

- [x] ✅ **Task 1.3**: `TestTheStopAxisIsNotVacuous` mirrors the original per
  shape: the Stop in-scope set is non-empty, the fixture is non-empty, and —
  the one that matters most — a teeth test proving `_arms_suppression` fires
  on three REAL declarations. Without it, a predicate that never returned True
  would make the whole Stop axis pass silently: the same vacuity, one level
  down.

### Phase 2: Narrow the prose patterns

- [x] ✅ **Task 2.1**: **The rule is: a match inside a QUOTED span does not
  declare.** Reached by eliminating the obvious answer first, with a
  measurement rather than an argument.

  Copying the token's fix — anchor to the declaration position — was tried on
  paper and REJECTED. Anchoring to the first sentence regresses two realistic
  legitimate stops ("everything I can do is done. Waiting on the user's
  decision about scope."), and Plan 00337's Non-Goals forbid regressing
  wordings that work today. Verified, not assumed.

  Quoting survives that test: an agent ASSERTS a blockage and CITES a phrase,
  and no legitimate declaration quotes itself. It also matches this plan's own
  Evidence, which describes "a stop message quoting `blocked only on human input`".

  Worth recording that this is the OPPOSITE call to `security_antipattern` and
  `sensitive_content`, which deliberately refuse a quoted-span exemption. The
  difference is real rather than inconsistent: there, quoted text can still
  EXECUTE, so the exemption would be a one-character bypass. Here the text is
  a message, never a program.

- [x] ✅ **Task 2.2**: Pinned twice, at both levels. The integration guard
  carries four quoting shapes; `TestCitingAPhraseIsNotDeclaringIt` covers the
  matcher directly, including the hazard the guard cannot see — **an
  apostrophe must never open a quoted span.** Two frozen patterns contain one
  (`the owner's input`, `the user's decision`), so naive single-quote pairing
  would swallow the phrase it exists to match and silently disable the
  patterns this narrowing is protecting.

- [x] ✅ **Task 2.3**: **A residue remains and is recorded as a decision, not
  left implicit.** An UNQUOTED sentence describing the mechanism ("the daemon
  drops a tick when a session is blocked only on human input") still arms. It
  is not lexically separable from "the release is blocked only on human
  input", which must arm — the difference is semantic. Asserted by
  `test_unquoted_prose_about_the_mechanism_still_declares`, whose docstring
  says that making it False later is an improvement rather than a regression.

  This is exactly why Plan 00337 added the sentinel and closed the patterns to
  extension: the residue is meant to be left alone, not chased.

## Success Criteria

- [x] A Stop handler that matches its own trigger vocabulary in prose is
  reported by the prose guard, with the same clarity as a PreToolUse one.
  Demonstrated, not asserted: the guard was written first and FAILED on three
  of its four quoting fixtures, naming `AutoContinueStopHandler` — the bug this
  plan was filed for, reproduced automatically for the first time.
- [x] The guard's scope is stated as a decision, and its non-vacuity tests
  cover every fixture shape it carries.
- [x] The prose-pattern question has an answer with a test behind it, and the
  part that cannot be narrowed has a recorded reason and its own assertion.
- [x] Full QA green (25/25) and the daemon restarted and verified before the
  terminal status flip. Daemon 1461157 → 1559459, RUNNING; tree unmodified
  between the run starting and finishing.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00342-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: Plan 00337 Phase 3, which hit this bug in its own implementation and
  fixed the instance while explicitly leaving the class to a follow-up.
- Prior art: Plan 00228 built the guard and chose its PreToolUse scope for a
  good reason that has since expired.
