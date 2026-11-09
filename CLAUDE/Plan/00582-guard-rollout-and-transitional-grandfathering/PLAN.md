# Plan 00582: guard rollout and transitional grandfathering

**Status**: Not Started
**Created**: 2026-11-09
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A guard that makes a repository invalid the moment it is switched on gets disabled, not obeyed. The branch guards
showed this: a repository with dozens of open branches against `branches.wip.cap: 10` was blocked from creating any
branch at all, with no way to adopt the guard gradually. The owner's direction: give a repository a recorded,
deadline-bound transition, and make that the standard approach whenever strictness is ratcheted up, rather than
reinventing it per guard.

The project already uses many rollout strategies, but each guard invents its own and none is written down as a set:
advise/warn/block modes with per-check overrides (`plan_workflow.qa`, `documentation.qa`), `block_once`
(`lsp_enforcement`), staged day thresholds (`branches.dormancy`), `MUST_..._BECAUSE` overrides (`comment_size`,
plan size), record-only simulation (Plan 00418), and three grandfather options in three shapes, all permanent:
`plan_workflow.journal.grandfather_before` (a number threshold), `plan_workflow.qa.legacy_plan_allowlist` (plan
numbers) and `documentation.qa.grandfather_allowlist` (globs, "forever"). `CLAUDE/HANDLER_DEVELOPMENT.md` covers
how a handler works, not how to introduce strictness.

Two different things are called grandfathering, and this plan keeps them apart. A **permanent legacy exemption**
covers history nobody will fix (old plans without a JOURNAL/). **Transitional grandfathering** is debt that must be
paid: a snapshot of what was invalid when the guard was enabled, recorded by a command, which only shrinks, carries a
deadline per entry, and is listed as an outstanding problem in every session. Past the deadline the normal deny
applies (owner ruling, 2026-11-09). Nothing is ever deleted by the mechanism itself.

Related: Plan 00420 owns the mode vocabulary (`block`/`warn`/`off` per rule) and the migrating config upgrade, and
this plan reuses that vocabulary rather than defining a second one. Plan 00144 (warn-to-block ratchet of
`commit_gate_mode`, dormant on a go/no-go) and Plan 00163 (`grandfather_before`) are adoption targets. GitHub #192
(branch-guard notices state no intent or action) is the first concrete instance of the doc's message standard and is
fixed separately. Prior art: Plans 00558 and 00571 (branch WIP cap and pools).

## Goals

- One canonical best-practice document for introducing or tightening a guard: the rollout strategies, when to use
  each, the message standard (every guard surface says why it fired and what to do next), and the migration path,
  linked from `HANDLER_DEVELOPMENT.md` and the documentation routing table.
- One shared, tested transitional-grandfather primitive: a command records the snapshot; the list only shrinks;
  each entry carries `recorded_at` and a deadline; SessionStart and the relevant sweep list every live entry with its
  days remaining; an expired entry gets the normal deny.
- The branch guards adopt it first (`branches.wip` cap, dormancy block stage, parked and merged pools): creating a
  branch is judged on the non-grandfathered branches, while grandfathered ones count down to their deadline.
- Upgrade and `optimise` offer to record the snapshot whenever a ratchet would turn the repository red.

## Non-Goals

- No change to Plan 00420's per-rule mode vocabulary, which this plan reuses.
- Permanent legacy exemptions are not removed. They move onto the primitive only where the review in Phase 4
  finds them transitional.
- No automatic deletion of any grandfathered item, branch or file.

## Tasks

### Phase 1: Best-practice document

- [ ] ⬜ **Task 1.1**: Inventory every rollout strategy in use (mode options, `block_once`, staged thresholds,
  overrides, simulation, grandfather options, standing authorisations), with file references
- [ ] ⬜ **Task 1.2**: Write the canonical guard-rollout document in the agent tree, including the message standard
  and the transitional-versus-permanent distinction; link it from `HANDLER_DEVELOPMENT.md` and `CLAUDE/CLAUDE.md`

### Phase 2: The shared primitive

- [ ] ⬜ **Task 2.1**: Design the record shape, its storage (tracked config or a tracked baseline file) and the
  recording verb; decide the deadline default and how a guard declares it
- [ ] ⬜ **Task 2.2**: RED tests, then build: record, shrink-only (a resolved entry cannot be re-added, a new item
  never joins), deadline expiry to the normal deny, and the SessionStart listing

### Phase 3: Branch guards adopt it

- [ ] ⬜ **Task 3.1**: RED tests, then build: the cap and dormancy judge non-grandfathered branches; grandfathered
  branches are listed with days remaining in `branch-sweep` and at stop time
- [ ] ⬜ **Task 3.2**: Upgrade and `optimise` offer the snapshot when the branch guards would block on enabling

### Phase 4: Existing grandfather options

- [ ] ⬜ **Task 4.1**: Classify the three existing options as permanent or transitional; migrate the transitional
  ones onto the primitive with a config migration, and document the permanent ones in the Phase 1 document

## Success Criteria

- [ ] The guard-rollout document exists, is linked from `HANDLER_DEVELOPMENT.md` and the routing table, and names
  every strategy found in Task 1.1
- [ ] A repository over the branch cap can enable the branch guards, record a snapshot, and create a branch, while
  every grandfathered branch is listed with its deadline; past the deadline the normal deny applies (tests prove both)
- [ ] The list cannot grow after recording (tested)
- [ ] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` for the new verb
  and config, and an upgrade-guide entry for any migrated option

## Delivery & Milestones

- (pending)
