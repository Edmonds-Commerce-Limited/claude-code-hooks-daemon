# Plan 00579: copy seeded files and worktree removal

**Status**: Blocked on the owner (the questions below)
**Created**: 2026-11-09
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #164

## Overview

`worktree_create` can seed a new worktree with files from the main checkout, as symlinks or as copies. When a merged,
clean worktree is removed, the `destructive_git` worktree-removal guard (R-GIT-WORKTREE-REMOVE-FORCE) refuses if an
ignored entry matches no `branches.cleanup_after_merge.regenerable` glob. Symlink-mode seeds are already skipped, but
copy-mode seeds are not. So a worktree whose only leftover is a seeded copy cannot be removed, and its merged branch then
cannot be deleted.

Verified on `main` at triage: `core/branch_cleanup.py` never reads the `worktree_create` seed entries. The only escape is
to repeat each seeded path in `regenerable`, a second list that drifts from the first.

Why it is not a plain defect: the guard is a safety control, and a copy-mode seed is NOT always regenerable. The
issue's own example is a file a tool writes permission grants into, which is why the copy is not a symlink. A copy that
has changed in the worktree holds content the seed list cannot recreate, so treating every copy-mode seed as regenerable
would let the guard delete real work.

Related issues filed the same day, to be triaged together: #167 (`check-worktree-seed` reports an `optional: true` seed
entry as missing) and #173 (`WorktreeCreate` cleanup cannot remove a worktree git left locked "initializing").

## Owner questions

- **Q1.** May the removal guard treat a copy-mode seeded file as regenerable? The proposed safe form: only while it is
  byte-identical to its source in the main checkout. A copy that has diverged still blocks and is named in the deny.
- **Q2.** If yes, should the seed list be read directly (one list, no drift), with `regenerable` still able to add to
  it?
- **Q3.** Should #167 and #173 be planned with this one, as one worktree-seed and creation pass?

## Goals

- To be set from the owner's answers.

## Non-Goals

- No change to the removal guard before the owner answers.

## Tasks

### Phase 0: Owner decision

- [ ] ⬜ **Task 0.1**: owner answers Q1-Q3; this plan is then re-planned into implementation phases

## Success Criteria

- [ ] The owner has answered Q1-Q3, and the plan carries implementation phases that follow those answers

## Delivery & Milestones

- (pending the owner)
