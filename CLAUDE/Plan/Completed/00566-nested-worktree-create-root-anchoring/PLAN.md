# Plan 00566: nested worktree create root anchoring

**Status**: Complete
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

- [x] ✅ **Task 1.1**: End-to-end test with real git: an outer worktree with symlink-mode seeds, then a handler call
  from inside it; plus a seed that genuinely escapes the repository (still rejected). Both PASS on unmodified `main`:
  the defect was already fixed (below), so there was no red run.
- [x] ✅ **Task 1.2**: Not needed. `_repo_root` already returns `GitRepo.main_worktree_root()` (the first
  `git worktree list` entry), from Plan 00474 N563 (`dc45486fa`), shipped in v3.72.0. The triage read the
  `_repo_root(cwd)` call site but not the method body; the reporter ran 3.71.0.
- [x] ✅ **Task 1.3**: No callout (no behaviour change); targeted QA green; tests merged; #161 answered "fixed in
  v3.72.0" and closed.

## Success Criteria

- [x] A nested worktree creation succeeds and is seeded, now pinned by a regression test (it already did on `main`).
- [x] Targeted QA passes (42/42 on the combined #161/#162 head).
- [x] No release-bound consequence: the behaviour shipped in v3.72.0 under N563, and this plan adds tests only, so no
  callout goes into the pending-release holding area.

## Delivery & Milestones

- Plan filed from issue #161 triage.
- Regression tests `34d012a19`, merged to main via `82673feec`. Plan complete as already delivered by N563.
