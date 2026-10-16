# Plan 00530: subagent tier enforcement follow up

**Status**: Not Started
**Created**: 2026-10-16
**Owner**: dev
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00472 shipped the subagent tier levers advisory-only: a per-dispatch tier
row in the shared spend ledger, `hooks-daemon tiers`, `subagent_tier_advisor`
and `workflow_fanout_advisor`. Its Fable rulings
([RULINGS-fable.md](../Completed/00472-subagent-model-tier-selection/RULINGS-fable.md),
section 3) moved everything that needs evidence a running session produces,
or an owner decision, into this follow-up plan.

Four items are here. First, confirm `workflow_fanout_advisor` against a real
PreToolUse(`Workflow`) payload: the handler's own probe writes the key names and
value types to `payload-capture/workflow-shape.json` on the first `Workflow`
call of a session. Second, decide a Workflow ceiling deny mode, only once that
shape is confirmed. Third, decide `require_explicit` for the tier advisory from
the hit rate its ledger events measure. Fourth, the `CLAUDE_CODE_SUBAGENT_MODEL`
flip with its teammate probe (472-B Tasks 1.3 and 1.4). The flip is the
owner's call.

## Goals

- The Workflow advisor's assumed payload shape is confirmed or corrected
  against a captured `workflow-shape.json`.
- Enforcement modes are decided from measured evidence, not added by default.

## Non-Goals

- Shipping a project `Explore` definition to clients (T7, left to the owner).
- Suggesting a spend up (T6, dropped by ruling D5).

## Tasks

### Phase 1: Evidence

- [ ] ⬜ **Task 1.1**: After an owner-opted-in `Workflow` run, read
  `payload-capture/workflow-shape.json` and the `workflow-fanout-advisor`
  verdicts. Confirm the `script`/`scriptPath`/`args` shape the handler assumes,
  or correct it, and add a fixture built from the captured shape.
- [ ] ⬜ **Task 1.2**: Probe whether `CLAUDE_CODE_SUBAGENT_MODEL` reaches
  agent-team teammates without `_FORCE`, and whether a hook subprocess sees
  it (472-B Tasks 1.3, 1.4).
- [ ] ⬜ **Task 1.3**: Measure the `tier-advisory` events' share of dispatches
  from the spend ledger over representative sessions.
- [ ] ⬜ **Task 1.4**: Close GitHub issue #58 when this plan's decisions
  are made. The Plan 00472 implementation summary is already posted on it
  (issue comment 6226619683), and it stays open because its enforcement and
  default-model questions are open here.

### Phase 2: Decisions

- [ ] ⬜ **Task 2.1**: Workflow ceiling deny mode: decide after Task 1.1.
- [ ] ⬜ **Task 2.2**: `require_explicit` for `subagent_tier_advisor`: open it
  only if Task 1.3 shows the advisory firing on more than a configured share
  of dispatches.
- [ ] ⬜ **Task 2.3**: The `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` flip in this
  repository's settings (owner's decision, informed by Task 1.2).

## Success Criteria

- [ ] The Workflow payload shape is confirmed against a captured payload, and a
  fixture from it is in the test suite.
- [ ] Each enforcement mode in Phase 2 is either built with its evidence cited
  or recorded as declined.
- [ ] Release-bound consequences of any mode built here are recorded in the
  pending-release holding area (`CLAUDE/UPGRADES/UNRELEASED/`); a plan that
  builds none has none, and says so.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00530-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Opened by the Plan 00472 build, per the Fable rulings' section 3.
