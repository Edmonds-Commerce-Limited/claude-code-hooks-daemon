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

- [x] ✅ **Task 1.1**: The ceiling is stated wherever a reader could
  re-litigate `durable: true` — handler docstring, `get_claude_md()`, config
  comment and this plan. `CronCreate` is a harness tool and cannot be
  unit-tested, so what IS pinned by test is that the advisory always explains
  *why* re-creation is needed (`test_it_says_why_the_job_has_to_be_recreated`);
  an advisory that omits the reason reads as noise and gets ignored.
- [x] ✅ **Task 1.2**: `persistent_crons` with `PersistentCronConfig`
  (id/schedule/prompt/enabled/description). Schedules validated as 5-field at
  load, blank id/prompt rejected, duplicate ids rejected.
- [x] ✅ **Task 1.3**: `persistent_cron_assertor`, priority 70. Asserts by
  instruction, and a test forbids wording that claims to know what is running —
  it caught my own first draft, whose disclaimer contained the banned phrase.
- [x] ✅ **Task 1.4**: Ships inert, but via ONE switch rather than two.
  `persistent_crons.enabled` is off by default and overrides each job's own
  flag; a second handler-level switch would create a state where a project that
  declared jobs AND enabled the section still silently got nothing.

### Phase 2: The SDLC runbook

- [x] ✅ **Task 2.1**: Labels `agent-triaged` / `agent-working` /
  `agent-needs-human`, created in the repo. Stale-`working` recovery is the
  FIRST selection rule, and it re-verifies state from git rather than trusting
  the label.
- [x] ✅ **Task 2.2**: Exactly one issue per tick, oldest-first, skipping
  anything labelled for a human.
- [x] ✅ **Task 2.3**: Six outcomes, not four — the dogfood added
  "blocked on upstream/external" and four pre-classification checks
  (reverted-before, still-true-today, part-of-a-cluster, partially-delivered).
  Each traces to a real issue on this backlog, recorded in Task 3.2.
- [x] ✅ **Task 2.4**: `setup_worktree.sh` plus an implementation sub-agent,
  briefed with verified facts rather than the raw issue body, and explicitly
  permitted to disagree with the brief.
- [x] ✅ **Task 2.5**: Close requires the fix commit to be an ancestor of the
  default branch AND CI success on that head, re-checked rather than trusted.
  A `cancelled` CI run is a supersession, not a failure.

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
