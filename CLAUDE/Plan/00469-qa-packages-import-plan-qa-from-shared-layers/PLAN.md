# Plan 00469: qa packages import plan qa from shared layers

**Status**: Not Started
**Created**: 2026-09-24
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct
**Graduated from**: [Plan 00422](../00422-niggles-ledger-fifteen/NIGGLES.md) N14, rows 1 and 2

## Overview

`utils` is the layer that both QA subsystems share. An import that runs from
`utils` or `docs_qa` INTO `plan_qa` makes the other subsystem depend on a
package it has no business loading. The ratchet in
`tests/integration/test_qa_package_dependency_direction.py` (`_KNOWN_EDGES`)
declares every surviving edge. An undeclared edge fails, and so does a
declared edge that has gone. Plan 00444 cleared two of the four edges by
splitting `GitFacts`. Two remain, and 00422 N14 left them open on purpose:
each needs a decision about where a thing belongs, not a mechanical move.

| Edge                                                    | Why it is there                                                    |
| ------------------------------------------------------- | ------------------------------------------------------------------ |
| `utils/goal_ledger.py` → `plan_qa.model`                | it reads a plan's status through `PlanDoc`                         |
| `docs_qa/checks/module_doc_budget.py` → `plan_qa.types` | it reuses plan QA's tier line-count constants so they cannot drift |

## Decisions (unattended, 2026-09-24; the owner can reverse either with one message)

1. **`goal_ledger` stays in `utils`; the status parse moves down.** The
   ledger is consumed by handlers, not by plan QA, so moving it into
   `plan_qa` would invert a different edge. It needs a plan's **Status**
   line, not the whole `PlanDoc` model. The status-line grammar moves into a
   `utils` module that `plan_qa.model` itself then uses, so the grammar still
   has one home.
2. **The tier constants move to a shared `utils` module** that both
   `plan_qa.types` and `docs_qa`'s budget check import. The two budgets stay
   bound to one definition, which was the whole reason for the import.

## Goals

- `_KNOWN_EDGES` is empty, and the ratchet still fails on any new edge.
- One definition each for the status grammar and the tier constants.

## Non-Goals

- Changing what the goal ledger records, or any budget value.

## Tasks

### Phase 1: Status grammar

- [ ] ⬜ **Task 1.1**: Starts after the 00466 goal-flip branch merges,
  because that branch rewrites `utils/goal_ledger.py`. TDD a `utils` status
  parser with the exact behaviour `PlanDoc` has today (pin it with tests
  taken from plan QA's own status tests). Point `plan_qa.model` and
  `goal_ledger` at it, and strike the row from `_KNOWN_EDGES`.

### Phase 2: Tier constants

- [ ] ⬜ **Task 2.1**: Move the tier line-count constants to a shared `utils`
  module. Re-export them from `plan_qa.types` so no plan QA caller moves.
  Point `module_doc_budget` at the shared module, and strike the row.

## Success Criteria

- [ ] `_KNOWN_EDGES` is empty, and
  `test_no_undeclared_module_imports_plan_qa` still fails on a planted edge.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00469-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Graduated from 00422 N14 with the evidence recorded there.
