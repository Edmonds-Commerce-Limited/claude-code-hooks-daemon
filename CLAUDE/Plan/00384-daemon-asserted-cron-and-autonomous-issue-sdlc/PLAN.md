# Plan 00384: daemon asserted cron and autonomous issue sdlc

**Status**: In Progress
**Created**: 2026-09-12
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus

## Overview

The owner asked for an hourly cron that picks up open GitHub issues and carries
each one through a full SDLC — triage, plan, implement in a worktree via
sub-agent, QA, review, merge to the default branch, then comment and close the
issue — with releases staying human-gated. They also asked whether such a cron
can be made persistent across sessions, and proposed the daemon asserting it if
not.

**It cannot be made persistent, and the proposed fallback is the only route.**
Claude Code's `CronCreate` documents its `durable` parameter as having no
effect: every job is session-only and in-memory, and recurring jobs auto-expire
after 7 days. So persistence is achieved the way the owner guessed — the daemon
DECLARES the crons it wants and asserts their presence at SessionStart, telling
the agent to recreate any that are missing. `recovery_cron_advisor` already
establishes this shape for the failsafe cron.

That splits the work in two. The declaration/assertion mechanism is a generic
daemon capability worth having on its own, and the issue SDLC is then just one
declared cron whose prompt invokes a skill holding the runbook.

Three design constraints come from the material rather than from taste, and
each one is a safety property rather than a preference:

- **An issue body is untrusted input.** This repository is public and its open
  issues come from outside reporters. A loop that reads an issue and then acts
  is a prompt-injection surface, so the runbook treats bodies as DATA and never
  as instructions.
- **One issue per tick.** Thirteen issues in one hourly tick would run for
  hours and exhaust context. A bounded tick also makes a crashed tick cheap to
  recover from.
- **Not every issue is autonomously fixable.** The live backlog includes a
  major dependency adoption, a design question and a research process. Triage
  must be able to stop at "plan filed, needs a human decision" rather than
  bulldozing a feature design.

## Goals

- The daemon declares crons in config and asserts them every SessionStart, so a
  new session re-establishes them without the owner remembering.
- An hourly tick takes ONE open issue from triage through to merged-and-closed,
  or stops at a recorded, labelled reason.
- An issue is never closed unless its fix is verifiably merged into the default
  branch.
- Releases stay human-gated; nothing in this loop publishes to users.

## Non-Goals

- Automating the release. `/release` stays the human gate, unchanged.
- Acting on instructions found inside an issue body. Bodies are evidence about
  a defect, never direction for the agent.
- Fixing feature requests and design questions autonomously. Those get a plan
  and a label, and stop.
- A general client-facing issue bot. The declaration mechanism ships; the
  issue runbook is this repository's own workflow.

## Tasks

### Phase 1: Daemon-declared, session-asserted crons

- [ ] ⬜ **Task 1.1**: Establish the ceiling honestly first — a test that pins
  what `CronCreate` can and cannot do, so no future reader re-litigates
  `durable: true`. The mechanism exists BECAUSE persistence does not.
- [ ] ⬜ **Task 1.2**: Config schema for declared crons: id, schedule, prompt,
  enabled. Validated like every other config surface.
- [ ] ⬜ **Task 1.3**: A SessionStart handler that emits the declared crons and
  instructs the agent to `CronList` and create any missing. It cannot read
  session memory, so it asserts by instruction, which is exactly how the
  failsafe cron advisory already works.
- [ ] ⬜ **Task 1.4**: Ship it default-OFF with no declared crons, so a client
  project gains nothing it did not ask for.

### Phase 2: The SDLC runbook

- [ ] ⬜ **Task 2.1**: Durable state on the issues themselves via labels, not a
  local file — a label survives a fresh clone and is visible to the humans
  watching the repo. Needs a stale-`working` recovery path, because a tick that
  dies mid-issue must not strand it forever.
- [ ] ⬜ **Task 2.2**: Selection: exactly one issue per tick, oldest-first among
  eligible, skipping anything labelled for a human.
- [ ] ⬜ **Task 2.3**: Triage classifier with an explicit STOP branch —
  duplicate, invalid, needs-human-decision, or actionable. #30/#31 are
  confirmed duplicates and are the dogfood case for that branch.
- [ ] ⬜ **Task 2.4**: Execute in a worktree via sub-agent, then QA, review,
  merge. Reuses the existing worktree and merge machinery rather than inventing
  a second path.
- [ ] ⬜ **Task 2.5**: Close only on verified merge into the default branch.
  The close step must re-check the merge rather than trust the earlier step.

### Phase 3: Dogfood on the real backlog

- [ ] ⬜ **Task 3.1**: Run the loop by hand against the live issues and fix what
  the run exposes, rather than declaring it correct from the design.
- [ ] ⬜ **Task 3.2**: Record what the dogfood changed, so the runbook's rules
  are traceable to an observed failure rather than to speculation.

## Success Criteria

- [ ] A fresh session re-establishes the declared crons from config alone.
- [ ] The mechanism ships inert for client projects.
- [ ] One tick processes exactly one issue and leaves it in a recorded state.
- [ ] An issue body carrying instruction-shaped text does not redirect the loop.
- [ ] No issue is closed without a verified merge to the default branch.
- [ ] The loop has been run against real issues and corrected from what it did.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  this plan records why it has none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Requested by the owner: hourly cron, full SDLC per issue, releases stay human.
- The persistence question is answered in the Overview: `CronCreate` cannot do
  it, so the daemon asserts instead.
