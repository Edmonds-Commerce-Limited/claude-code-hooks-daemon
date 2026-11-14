# Plan 00605: branch sweep classifies no merge base branches

**Status**: Not Started
**Created**: 2026-11-14
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #203

## Overview

The branch inventory (`src/claude_code_hooks_daemon/core/branch_inventory.py`) measures each work branch against
each target with `_pair_facts`. That includes a three-dot `git diff --shortstat <target>...<tip>` in `_lines`. When
the tip shares no history with the target (an orphan branch, or any branch after the default branch's history was
rewritten), git exits non-zero with "no merge base". `_lines` returns `None`, so `_pair_facts` returns `None`, and
the branch is left `UNCLASSIFIED` with `_UNMEASURED_REASON`, which blames the sweep budget. Raising
`branches.sweep.budget_ms` cannot help.

An unclassified branch still counts toward the open-work pool, so a repository full of them stays over
`branches.wip.cap`. That blocks branch creation, and the sweep gives no way to clear it.

`branch-sweep` also has no way to override `branches.sweep.budget_ms` for a single run. The SessionStart
`branch_sweep` handler reads the same configured value.

## Goals

- A branch with no merge base against a target is measured, and classified as unmerged work that the target does
  not contain. Its commits are counted, and no error is reported.
- When a pair still cannot be measured, the record's reason names the real cause: the budget ran out, there is no
  merge base, or git returned a named error. One generic sentence blaming the budget is no longer used for all three.
- `branch-sweep --budget-ms N` overrides the configured budget for that run only. The configured value and the
  SessionStart handler are unaffected.

## Non-Goals

- No change to classification of branches that do share history with the target.
- No change to the WIP, parked or merged caps, or to what counts toward them.
- No change to `delete-branch` proofs.

## Tasks

### Phase 1: reproduce and fix

- [ ] ⬜ **Task 1.1**: A failing test reproduces the issue. An orphan branch in a temporary repository comes back
  `UNCLASSIFIED` with the budget reason, even though the budget is far from spent.
- [ ] ⬜ **Task 1.2**: Measure a no-merge-base pair without the three-dot diff. Lines come from a two-tree diff, or
  are left unmeasured with a stated reason. Ahead and unique counts come from the existing log and cherry walk,
  which work without a merge base. The branch then classifies as unmerged work.
- [ ] ⬜ **Task 1.3**: Each reason for an unmeasured pair says which cause applied: the budget, no merge base, or a
  git error.
- [ ] ⬜ **Task 1.4**: Add a `branch-sweep --budget-ms N` flag (a positive integer) that applies to that run only,
  with tests.
- [ ] ⬜ **Task 1.5**: Add a release note under `CLAUDE/UPGRADES/UNRELEASED/release-notes/`, and update any doc that
  states the unclassified reason or lists `branch-sweep`'s flags.

## Success Criteria

- [ ] The orphan-branch reproduction test fails before the fix and passes after it.
- [ ] Targeted QA (`./scripts/qa/llm_qa.py changed`) passes on the branch, and main CI is green after the merge.
- [ ] The pending-release holding area carries a release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` for
  the classification change and the new flag.
- [ ] GitHub #203 is commented and closed.

## Delivery & Milestones

- Not started.
