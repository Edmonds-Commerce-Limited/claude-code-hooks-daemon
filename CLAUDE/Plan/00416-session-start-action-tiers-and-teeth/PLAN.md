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

- [ ] ⬜ **Task 2.1**: Point `persistent_cron_assertor` at Task 1.1's checker as
  its verifier, so the cron case flows through the computed tier rather than
  being special-cased.

- [ ] ⬜ **Task 2.2**: Classify the remaining handlers. Candidates for a
  verifier beyond crons: `project_handler_load_checker` and
  `hook_registration_checker` — both mean the session is not protected as
  configured. Everything else starts `ACTION_SUGGESTED` or `INFO` and earns a
  promotion only by supplying a verifier.

- [ ] ⬜ **Task 2.3**: The supervisor directive, and dogfood it in this
  repository. Ship the nudge; the Stop block is what makes it more than a nudge.

## Success Criteria

- [ ] ⬜ Deleting a declared cron and ending the session blocks the stop, with a
  message naming the exact `CronCreate` to run.

- [ ] ⬜ `bin/hooks-daemon session-actions` lists exactly the failing-verifier
  items and nothing else.

- [ ] ⬜ A handler with no verifier cannot produce `ACTION_REQUIRED`, proven by
  test rather than by review convention.

- [ ] ⬜ An absent `session_crons` does not produce a block — proven, because
  absent-is-not-empty is the trap most likely to make this nag wrongly.

- [ ] ⬜ Full QA passes, the daemon restarts, CI green.

## Delivery & Milestones

- Carries N6 and N15 forward from ledger
  [00413](../Completed/00413-niggles-ledger-thirteen/PLAN.md), whose design document moved
  here with them. The ledger was the wrong home once this became feature work.

- Issues #22/#23 (delivery) are closed and fixed. #32 stays OPEN as the tracking
  issue for this work: its diagnosis — that the model ignores SessionStart
  messages — is correct, and only its proposed remedy (reframe them as
  human-only) is superseded.
