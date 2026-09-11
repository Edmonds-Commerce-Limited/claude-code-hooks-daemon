# Plan 00377: niggles ledger

**Status**: In Progress
**Created**: 2026-09-11
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Main Thread

## Overview

**This is the open niggles ledger. A small defect found in passing is recorded
here, in the same turn it is found — never reported only in chat.**

A defect mentioned in conversation and nowhere else is lost the moment the
context window rolls. It reads as diligence ("worth knowing about…") while
producing exactly the same outcome as saying nothing: nobody can act on it, no
one can find it later, and the next agent rediscovers it from scratch. Several
real defects in this repository were surfaced that way and survived only
because someone happened to re-notice them.

A niggle is a defect too small to deserve its own plan: a missing check, an
invariant nothing enforces, a message that misleads, a tool with a blind spot.
It is still a defect. The ledger is the standing home for them, so recording
one costs an append rather than a whole plan.

**Lifecycle** — see `CLAUDE/PlanWorkflow.md` ("The niggles ledger") for the
authoritative rule:

- Exactly one niggles ledger is open at a time.
- When every entry is resolved, the ledger closes and is archived like any
  other plan.
- The next niggle found opens a NEW ledger. Do not reopen a closed one.

## Goals

- Every small defect found in passing is recorded the moment it is found.
- No defect exists only as chat output.

## Non-Goals

- Absorbing work that deserves its own plan. A niggle that turns out to be
  systemic graduates to its own plan and is struck from here with a pointer.
- Being a wish-list. This is defects, not ideas or preferences.

## Tasks

### Phase 1: Open niggles

- [x] ✅ **N1: `plan-qa --sweep` does not check journal entry ordering.** The
  journal preamble states the grammar "times increase down the file", and
  nothing enforced it. Measured: a `00376` day-file whose entries ran
  12:49 → 12:58 → 13:00 → 12:50 passed `plan-qa --sweep` with `0 findings`.
  The `journal-append-only` check correctly caught the EDIT that caused it, so
  the gap was specifically in the sweep. **Fixed**: new check
  `journal-entry-ordering`, registered at EDIT and SWEEP, advise, honouring
  `journal.mode: block`. Fenced blocks and the blockquoted grammar example are
  not entries; equal times pass.

  Two deliberate blind spots, each guarded by a test: archived plans are
  skipped (`archive-immutability` forbids the edit that would fix them), and
  day-files named before the rule shipped are grandfathered, mirroring Plan
  00163 Decision 7's no-backfill. The second was not a convenience — running
  the check over this repo showed the pre-existing journals have the narrative
  order RIGHT and the clock readings wrong, so the only available "fix" was
  inventing timestamps in an append-only record. A permanently unfixable
  finding trains readers to ignore the check.

- [x] ✅ **N2: the plan-dedupe scout cannot see completed plans.** It read
  only plans in the plan root and reported "Checked N live plans". For the
  question it is most often asked — "does this machinery already exist?" — a
  COMPLETED plan is the likelier home, because the machinery exists precisely
  because a plan finished. Measured: it reported "No existing plan covers this"
  for Plan 00376's pre-upgrade work while Plan 00062 (Complete) had already
  built a pre-upgrade validation phase and the very confirmation gate 00376 is
  about. **Fixed**: the template gained step 3b — a cheap
  `grep -ril` over `Completed/*/PLAN.md`, reported under a mandatory
  `## Prior art (completed plans)` heading kept separate from duplicate
  candidates, because prior art means "read this first", not "do not file".

- [x] ✅ **N4: `agents install` cannot restore a drifted agent — it recommends
  itself.** When a deployed agent no longer matched a shipped revision, the
  daemon refused to touch it and advised running
  `hooks-daemon agents install <name>` — the command that just refused, so it
  failed again (exit 1). Reproduced on `hooks-daemon-plan-dedupe-scout`.
  **Fixed**: `agents install <name> --force` discards a customised copy and
  restores the shipped revision, saying that it did. The refusal itself is
  kept and is correct — a bulk refresh must never clobber local edits — so
  `force` defaults to False and only an explicitly named, explicitly forced
  install overwrites. The warning now names that escape instead of itself.

- [x] ✅ **N5: no dev-loop command redeploys the core docs.**
  `deploy_core_docs_if_enabled` is invoked only from `scripts/install_version.sh:684`
  and `scripts/upgrade_version.sh:423,1103`. Editing
  `install/templates/core/*.core.md` therefore leaves the deployed
  `CLAUDE/core/*.core.md` stale until the next install or upgrade, with nothing
  reporting the drift — `deploy-plan-workflow` does not cover core docs and a
  daemon restart does not either. Agents have `agents install`; core docs had
  no equivalent. **Fixed**: new `hooks-daemon deploy-core-docs` verb — the
  dev-loop refresh for `CLAUDE/core/*.core.md`. Client-owned overrides are
  untouched; only daemon-owned files are rewritten.

- [ ] ⬜ **N6: nothing reports that a deployed artefact has drifted from its
  template.** N5's verb makes the drift FIXABLE; it does not make it visible,
  so a stale deployed file still goes unnoticed until someone happens to
  redeploy. Measured while fixing N5: the same stale header sentence was
  sitting in `CLAUDE/Plan/mkplan.bash` AND in the deployed dedupe-scout agent,
  unreported. The agent surface is the only one that notices at all — it
  classifies as `CUSTOMISED` — and it cannot distinguish "the user edited this"
  from "the template moved on", which is why its warning accused the daemon's
  own deployed file of being hand-hacked. A drift check would most naturally
  live where the other whole-tree checks already run.

- [ ] ⬜ **N3: `upgrade.md` never mentions post-upgrade tasks.** The
  agent-facing upgrade procedure omits the step entirely, so the tasks are not
  read even by an agent following the procedure exactly. (Tracked in Plan 00376
  Task 4.3 as part of the upgrade rework; listed here so the ledger is a
  complete index of known small defects, and to be struck when 00376 lands it.)

## Success Criteria

- [ ] Every entry above is either fixed or graduated to its own plan.
- [ ] No niggle in this repository exists only as chat output.

## Delivery & Milestones

- Opened on the owner's ruling: "record ALL defects, never just casually tell
  me about them without recording them… we should always have an active plan
  that is collecting small niggles".
