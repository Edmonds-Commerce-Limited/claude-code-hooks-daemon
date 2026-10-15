# Plan 00528: worktree guard stale binding

**Status**: Complete
**Created**: 2026-10-15
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Field report from the desktop team's md-viewer seat (daemon 3.69.0), relayed by the coordinator. A general-purpose
sub-agent dispatched into the main checkout with no isolation created a probe worktree with Bash, wrote a throwaway
test file in it, removed the probe, and then had its report write into the main checkout denied with
R-SUBAGENT-CROSS-WORKTREE-WRITE. The deny named the removed probe as the agent's own worktree.

Cause: `subagent_worktree_write_guard` binds each `agent_id` to the linked worktree of its first
`Write`/`Edit`/`NotebookEdit` (ledger 00474 N282, trust on first use) and never re-checked that the bound worktree
still exists. The existing test `test_a_bound_agent_is_denied_the_main_working_tree` pins the binding half of the
sequence.

This plan exists because the open niggles ledger (00474) is tied to issue #59, which is assigned to another account,
and a release note must name a plan.

## Goals

- A binding whose worktree is no longer on disk is dropped, and the call is judged as an unbound one.
- A binding whose worktree still exists is unchanged.

## Non-Goals

- Treating a worktree the agent created itself as scratch that never binds. That needs the guard to learn of
  `git worktree add` from a Bash event, and it weakens the N282 protection for agents told to make their own
  worktree. Recorded as follow-up; the resident guidance now tells sub-agents not to write inside a probe.

## Tasks

### Phase 1: drop stale bindings

- [x] ✅ **Task 1.1**: Failing tests: a removed worktree releases the binding; a live probe keeps it.
- [x] ✅ **Task 1.2**: `_crossing` drops a binding whose root no longer resolves to the bound checkout.
- [x] ✅ **Task 1.3**: Resident guidance and module docstring updated; release note 064.

## Success Criteria

- [x] The md-viewer sequence (bind to probe, remove probe, write into main tree) is allowed, pinned by
  `test_a_binding_to_a_removed_worktree_is_dropped`, observed red before the fix.
- [x] Release-bound consequences recorded in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` as note 064.

## Delivery & Milestones

- Fix, tests and release note: see the plan's commits on main.
