# Plan 00394: failsafe cron coverage starts at first plan write

**Status**: Not Started
**Created**: 2026-09-13
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

The failsafe recovery cron is the net that resumes a session stalled by a rate
limit, a usage limit, an API error or a network failure. **A session only gets
that net once it writes or edits a plan file.** Until then there is no cron, and
nothing says so — the symptom of the gap is a session that simply never resumes.

The cause is that the crons this project relies on are established by handlers
on DIFFERENT hook events, and only one of them is a session-start event:

| Cron                | Established by               | Hook event   | Fires                               |
| ------------------- | ---------------------------- | ------------ | ----------------------------------- |
| `issue-sdlc`        | `persistent_cron_assertor`   | SessionStart | every session, unconditionally      |
| failsafe recovery   | `recovery_cron_advisor`      | PostToolUse  | only on a plan-lifecycle moment     |
| background watchdog | `background_process_tracker` | PostToolUse  | only when a process is backgrounded |

`recovery_cron_advisor.matches()` returns True only when
`_detect_lifecycle_phase(...)` finds a plan CREATION, PROGRESS or COMPLETION
moment, which requires a Write/Edit of a plan file (or `mkplan.bash`). No
handler in `handlers/session_start/` mentions the failsafe or recovery cron at
all — checked against the directory listing, which is recorded in the journal.

## This contradicts a claim in Plan 00384, and that is the finding

Plan 00384 built `persistent_crons` precisely because `CronCreate` cannot
persist a job — `durable` has no effect and recurring jobs expire after 7 days.
It declared exactly one job, and justified leaving the failsafe cron out:

> the daemon DECLARES the crons it wants and asserts their presence at
> SessionStart, telling the agent to recreate any that are missing.
> `recovery_cron_advisor` already establishes this shape for the failsafe cron.

**Half of that is true.** `recovery_cron_advisor` does supply a daemon-authored
verbatim prompt, exactly as the declaration mechanism does. But "this shape" was
defined in the same sentence as *asserting at SessionStart*, and the advisor
does not do that — it is a PostToolUse handler. So the failsafe cron was left
undeclared on the strength of an equivalence that does not hold for the only
property that matters here: surviving the start of a new session.

This was a reasoned decision, not an oversight, and it is recorded that way
deliberately — 00384 considered the failsafe cron and made a call, and the call
rests on a mis-stated equivalence.

## The counter-argument, recorded so the ruling is made on both

A failsafe cron resumes *work*; if a session is doing no plan work, there may be
nothing to resume, which would make the gap harmless. That argument is real but
does not survive contact with what sessions here actually do:

- An `issue-sdlc` tick does substantial work and may stall long before it ever
  writes a plan file.
- A `/release` run, a code review, a QA investigation or a long question-and-
  answer session can all stall with no plan write at all.
- Even a session that WILL do plan work is uncovered between session start and
  its first plan write, which is exactly when context-building happens.

So the exposure is narrower than "always", and it is not empty.

## The open question — why this is Not Started

Three fixes with materially different blast radii, and the choice is the owner's
because it decides whether this is a config change to one repository or a
product change every client receives:

1. **Declare the failsafe cron in this repo's `persistent_crons.jobs`.** Config
   only, no code, immediately effective, reversible. Fixes this repository and
   nothing else — every client project keeps the gap.
2. **Give `recovery_cron_advisor` a SessionStart counterpart** so the advice
   lands at session start as well as at plan-lifecycle moments. Fixes every
   project. Costs a new handler and a decision about whether the two surfaces
   may both speak in one session.
3. **Ship the failsafe cron as a daemon-DEFAULT declared job**, so
   `persistent_crons` carries it out of the box. The most complete fix and the
   most opinionated — it makes the daemon assert a cron in projects that never
   asked for one.

Option 1 is not exclusive with 2 or 3; it is the cheap local mitigation that
could ship first. Recorded as options, not a recommendation.

## Goals

- A session has failsafe recovery coverage from its start, not from its first
  plan write.
- Whatever establishes it states it once per session and never causes a
  duplicate cron — the reconcile-with-`CronList`-first rule must still hold.
- Plan 00384's mis-stated equivalence is corrected where it is written down, so
  the next reader does not re-derive the same wrong conclusion.

## Non-Goals

- Making crons genuinely durable. `CronCreate` cannot do it; this plan works
  within that limit rather than fighting it.
- Changing the failsafe prompt's wording or its no-op semantics.
- The background watchdog's prompt, which is deliberately agent-composed — see
  Plan 00388's provenance table. Declaring it would mean fixing wording the
  daemon currently leaves open on purpose, so it is a separate decision.

## Tasks

### Phase 1: Owner decision

- [ ] ⬜ **Task 1.1**: Owner picks option 1, 2, 3, a combination, or names
  another. Nothing below starts until then — the choice decides whether the
  work is a config edit or a new handler with its own test matrix.

### Phase 2: Fix, once decided

- [ ] ⬜ **Task 2.1**: A failing test first, pinning that a session with NO
  plan-file activity is still told to establish the failsafe cron.
- [ ] ⬜ **Task 2.2**: Implement the chosen option.
- [ ] ⬜ **Task 2.3**: Pin that the advice cannot produce two failsafe crons
  when every relevant surface speaks in one session.
- [ ] ⬜ **Task 2.4**: Correct the equivalence claim in Plan 00384's archived
  PLAN.md, or record the correction where a reader of it will find it.

## Success Criteria

- [ ] A session that never touches a plan file is still told to establish the
  failsafe recovery cron.
- [ ] Exactly one failsafe cron results when every relevant surface fires in one
  session.
- [ ] The claim that `recovery_cron_advisor` "already establishes this shape" is
  corrected wherever it is written down.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  this plan records why it has none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Graduated from [Plan 00393](../00393-niggles-ledger-seven/PLAN.md) N1, which
  recorded the asymmetry; the diagnosis that turned it from "looks like an
  oversight" into "a reasoned decision resting on a mis-stated equivalence" is
  what made it too large for the ledger.
- Found by asking whether a terminal crash had exercised the cron declaration
  machinery. It had not — the session was RESUMED, so every cron came back with
  its original ID. Chasing why the limitation had not bitten is what exposed
  that the most safety-critical cron has no session-start coverage.
