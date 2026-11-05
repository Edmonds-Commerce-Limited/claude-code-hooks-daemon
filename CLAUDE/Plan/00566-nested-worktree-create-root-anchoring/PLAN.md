# Plan 00566: nested worktree create root anchoring

**Status**: In Progress
**Created**: 2026-11-05
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #161

## Overview

When an agent working in a daemon-created worktree dispatches a sub-agent with `isolation: worktree`, the
`worktree_create` handler fails with `WorktreeSeedError`: every seed entry "resolves outside the repository root". The
cause is that the handler takes its root from `git rev-parse --show-toplevel` (`_repo_root` via `GitRepo.resolve_for`).
Inside a linked worktree, that is the worktree itself, not the main checkout. The seed sources are therefore the outer
worktree's own seeded symlinks, which resolve to the main checkout and fail the containment check. The same root also
places the nested worktree inside the outer worktree's tree. In practice this left the #152 fix without an independent
review, because no review agent could be started from inside its worktree.

The fix anchors the root on the main checkout (the repository's common git dir) both for the seed sources and for the
worktree parent, so a nested creation behaves exactly like a first-level one.

## Goals

- `worktree_create` invoked from inside a linked worktree creates a correctly seeded worktree under the MAIN checkout's
  worktree parent, with seed sources read from the main checkout.
- First-level creation is unchanged.
- The containment check still rejects a seed entry that really resolves outside the repository.

## Non-Goals

- Changing seed modes, entries or the `optional` semantics.

## Tasks

### Phase 1: Fix

- [ ] ⬜ **Task 1.1**: Failing test reproducing the issue: create an outer worktree with symlink-mode seeds, then
  invoke the handler with `cwd` inside it; assert a seeded inner worktree is created under the main checkout's worktree
  parent. Also cover a seed that genuinely escapes the repository (still rejected).
- [ ] ⬜ **Task 1.2**: Resolve the main-checkout root (common git dir) in the handler and use it for seed sources and
  the worktree path; check any other `_repo_root` callers in the same handler.
- [ ] ⬜ **Task 1.3**: Release callout; targeted QA; merge; comment and close #161.

## Success Criteria

- [ ] A nested worktree creation succeeds and is seeded, proven by a test that failed before the fix.
- [ ] Targeted QA passes.
- [ ] Release-bound consequence recorded in the pending-release holding area: a callout under
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- Plan filed from issue #161 triage.
