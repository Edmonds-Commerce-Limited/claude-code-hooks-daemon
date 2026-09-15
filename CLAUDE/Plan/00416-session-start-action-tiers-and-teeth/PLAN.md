# Plan 00416: session start action tiers and teeth

**Status**: In Progress
**Created**: 2026-09-15
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

SessionStart output reaches the model correctly — Plan 00271 Task 2.7 moved it
onto `hookSpecificOutput.additionalContext` at `61fd2c07`, which fixed issues
#22 and #23. **Delivery was never the remaining problem. Being ACTED ON is.**

Twenty-five SessionStart handlers emit into one flat block with no priority
signal. An agent reads it and weighs it as background, because injected context
is background: it is scenery, not a turn. This session is the evidence — the
block said "Run CronList FIRST" and the agent did not, until a completely
unrelated `PostToolUse` advisory told it to, much later.

The owner's ruling names the mechanism:

> there's a very large amount of session start output, but in my experience
> claude itself totally ignores this — it's mainly for humans

> the system MUST have teeth or its pointless

So rewording is not on the table; it was never an information problem. Two
things change: messages gain a TIER so the must-do set is short and nameable,
and the must-do set gets VERIFIED rather than merely re-asked.

## The design

**`ACTION_REQUIRED` is computed, never declared.** A handler does not choose the
tier — it optionally implements a verifier, and a message is `ACTION_REQUIRED`
exactly when a verifier exists and is currently failing. This is the owner's
Option B, chosen over "handlers declare a tier, reviewers police it" because a
declared tier inflates: every author believes their advisory is required, and a
tier that everyone claims is the flat noise we started with, one word longer.

Computing it removes the judgement call, so there is nothing to police.

Two criteria fall out, and both are needed:

- **Verifiable** — the admission test. Something on disk or in a hook payload
  can distinguish "done" from "not done". `skill_opportunity_detector` can never
  qualify: nothing separates "considered and declined" from "ignored".
- **Objectively required** — the session is MIS-CONFIGURED, not merely
  improvable. This is what keeps the QA sweeps out. `plan_qa_sweep` is trivially
  verifiable (re-run it), but plan drift is a judgement call about when to fix,
  not a broken session.

`ACTION_SUGGESTED` and `INFO` stay author-chosen, because neither carries
enforcement and therefore neither can be gamed into teeth.

### The three layers

1. **SessionStart** tags each message with its tier. Free, and already delivered.
2. **The supervisor** sends one turn-level directive after session start: *read
   the session start output and action all ACTION_REQUIRED items*. This works
   because of CHANNEL, not volume — the owner proved it on another machine with
   a single typed line, after which the agent ran `CronList`, created the job,
   confirmed it, and continued through the remaining items unprompted.
3. **Stop** verifies. A failing verifier at `Stop` blocks the stop. This is the
   tier that does not depend on compliance at all.

## Goals

- A session whose declared persistent crons are absent cannot end quietly: the
  stop is blocked, naming the exact `CronCreate` to run.

- An agent can re-fetch the must-do list on demand, without scrolling back
  through context, via one command.

- `ACTION_REQUIRED` is impossible to claim without supplying the check that
  proves the action happened.

## Non-Goals

- **Rewording advisories.** The information was never missing. Any change that
  amounts to saying it louder is out of scope by construction.

- **Blocking at SessionStart.** SessionStart cannot block, and should not: a
  mis-configured session must still start so it can be fixed.

- **Making every handler verifiable.** Most should stay `ACTION_SUGGESTED` or
  `INFO`. A small required set is the point, not a milestone on the way to a
  large one.

- **The `when_env:` key and the `issue-sdlc` branch-ref claim.** Those rode in
  with N6 and are a separate concern about cron DUPLICATION across machines.
  They stay owner-gated and are not part of this plan.

## Tasks

### Phase 1: The two independent halves (parallel)

- [x] ✅ **Task 1.1**: Stop-time cron enforcement, per
  [DESIGN-cron-enforcement.md](DESIGN-cron-enforcement.md). Compare declared
  `persistent_crons` against the `session_crons` the `Stop` payload carries;
  block the stop on a mismatch, naming the exact `CronCreate`. Three contract
  constraints are already established and must be respected: `session_crons`
  reaches `Stop`/`SubagentStop` only; `prompt` is capped at 1000 chars with a
  `… [+N chars]` marker, so exact equality never matches this project's own
  long prompt; and an ABSENT list must never be read as "no crons exist".

- [x] ✅ **Task 1.2**: The tier mechanism — an optional verifier on a
  SessionStart handler, `ACTION_REQUIRED` computed as "verifier exists and is
  failing", tier rendered into the emitted block, and a
  `bin/hooks-daemon session-actions` verb that prints just the required items so
  the supervisor can name a command instead of relying on context recall.

### Phase 2: Wire together and dogfood

- [ ] ⬜ **Task 2.1**: ~~Point `persistent_cron_assertor` at Task 1.1's checker
  as its verifier~~ — **buildable, and permanently failing. Declining it is a
  design call, not a missing mechanism.** An earlier statement of this task
  called it "not buildable" and reasoned that a verifier with nothing to verify
  against "cannot fail". Both halves are wrong, and in opposite directions:
  wiring it up works, and the verifier fails on every session without exception.

  `find_missing_crons(declared, session_crons)` returns the declared jobs it
  could not match. `SessionStart` delivers no `session_crons`, so the list is
  empty and *every* declared job comes back missing — proven, not inferred:
  `find_missing_crons([job], [])` returns `[job]`. Combined with `matches()`,
  which fires whenever the project declares any job at all, the verifier is
  failing at every session start, for ever. That computes `ACTION_REQUIRED`
  unconditionally — the opposite failure to a permanent `INFO`, and the worse
  one: a tier that is always at its maximum carries no information, and the
  flat-noise problem this plan exists to fix arrives one word louder.

  The honest options are unchanged: leave the cron case OUT of the computed
  tier and let the Stop block carry it alone (the tier system is for things
  checkable at session start, and this is not one); or give the assertor a
  different, genuinely-SessionStart-checkable verifier — but nothing at that
  point in the lifecycle can see a session's crons, so there may be no such
  signal to find. Owner-gated between the two.

- [x] ✅ **Task 2.2**: Classify the remaining handlers. Both named candidates
  now carry real verifiers, RED first: `project_handler_load_checker` (guards
  the project declared are OFF) and `hook_registration_checker` (events never
  reach the daemon). Each is the admission test's "objectively mis-configured"
  rather than "improvable" — an agent reading past either works without
  protections it has every reason to assume are live.

  Both declare `ACTION_SUGGESTED` as a floor, raised to `ACTION_REQUIRED` only
  by the verifier. Everything else keeps no verifier and stays `INFO`,
  which is the promotion rule working as designed rather than an omission.

  `hook_registration_checker`'s verifier deliberately SKIPS the migrate/repair
  path `handle()` runs, and a test pins that `settings.json` is byte-identical
  afterwards: a tier is also computed by `session-actions`, which a human runs
  to inspect a session, and rewriting their settings as a side effect of asking
  "how urgent is this?" would be indefensible.

  Verified live on this session, not only in tests: `session-actions` reports
  no ACTION_REQUIRED items, which is correct here and shows the mechanism does
  not false-alarm on a healthy session.

- [x] ✅ **Task 2.3**: The supervisor directive, shipped as a sixth signal
  family: `session_actions_directive` (SessionStart, priority 72) writes a
  `<session>.session-actions` signal, and the supervisor types one fixed
  directive as a real user-role line. Enabled in this repository's own config,
  opt-in everywhere else — it types into a human's terminal.

  **The payload is a positive integer and nothing else.** That is the
  `operator-signal` shape rather than the `goal-intent` one, and it was chosen
  rather than inherited: a nudge whose whole message is "go read what you were
  already told" never needed to carry prose, and a channel that cannot carry
  prose cannot later be widened into one. A test writes a signal carrying
  forged `message` and `rendered_lines` fields and asserts the rendered output
  is byte-identical to the fixed template.

  Three conditions gate the write, and the third is the one that keeps it from
  being litter: a verifier is failing, the handler is enabled, AND an armed ccy
  supervisor is live to read the signal. Without a supervisor nothing would
  ever consume the file.

  Priority 72 is load-bearing, not tidiness: `hook_registration_checker`
  SELF-HEALS inside its own `handle()`, so counting anywhere but last would
  nudge the agent about a problem the session had already fixed.

  The count comes from the same collector `hooks-daemon session-actions` uses,
  extracted to `utils/session_action_items.py` and pinned by test. The
  directive's entire content is *go action those items*; a directive that fired
  while that command reported nothing would teach the agent to ignore the next
  one, which is the exact failure this plan exists to fix.

## Success Criteria

- [x] ✅ Deleting a declared cron and ending the session blocks the stop, with a
  message naming the exact `CronCreate` to run. Proven by test
  (`TestADeclaredCronAbsentFromSessionCronsBlocks`) and observed live — though
  the live observation arrived as a DEFECT: the enforcer blocked every stop in
  this session on the day it merged (00419 N4), because the delivered prompt is
  re-rendered and matching compared bytes. The block and its `CronCreate`
  message worked exactly as designed; what was wrong was the comparison
  deciding a present cron was absent.

- [x] ✅ `bin/hooks-daemon session-actions` lists exactly the failing-verifier
  items and nothing else. Its baseline against this repository's real handler
  set is EMPTY, which since Task 2.2 means something stronger than "nothing has
  a verifier": two handlers ship one and both are currently passing.

- [x] ✅ A handler with no verifier cannot produce `ACTION_REQUIRED`, proven by
  test rather than by review convention — including the defence-in-depth case
  where `declared_tier` is set to `ACTION_REQUIRED` directly, which is clamped
  to `INFO` and logged at ERROR.

- [x] ✅ An absent `session_crons` does not produce a block — proven
  (`TestAbsentSessionCronsNeverBlocks`), alongside its mirror image: a PRESENT
  but empty list is real information and DOES block. Absent-is-not-empty is the
  trap most likely to make this nag wrongly, and the pair is what pins it.

- [ ] ⬜ Full QA passes, the daemon restarts, CI green.

## Delivery & Milestones

- Carries N6 and N15 forward from ledger
  [00413](../Completed/00413-niggles-ledger-thirteen/PLAN.md), whose design document moved
  here with them. The ledger was the wrong home once this became feature work.

- Issues #22/#23 (delivery) are closed and fixed. #32 stays OPEN as the tracking
  issue for this work: its diagnosis — that the model ignores SessionStart
  messages — is correct, and only its proposed remedy (reframe them as
  human-only) is superseded.
