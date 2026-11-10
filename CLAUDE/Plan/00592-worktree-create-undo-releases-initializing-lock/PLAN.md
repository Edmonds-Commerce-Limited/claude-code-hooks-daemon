# Plan 00592: worktree create undo releases initializing lock

**Status**: In Progress
**Created**: 2026-11-10
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #173

## Overview

When `git worktree add` fails or is killed by the 30s `Timeout.GIT_WORKTREE`,
`WorktreeCreateHandler._undo_failed_add` (`handlers/worktree_create/worktree_create_handler.py`)
runs `worktree remove --force`, `worktree prune`, `branch -D`. A killed add leaves
the worktree locked with reason `initializing`, and git refuses all three
(reproduced: `cannot remove a locked working tree … use 'remove -f -f'`; prune
keeps it; `branch -D` refuses a checked-out branch). Each failure is only
logged, so the half-made worktree and branch stay behind in exactly the case
the undo exists for.

## Goals

- The undo releases only git's own interrupted-add lock (reason exactly
  `initializing`, on the path this call created), then removes the worktree and
  deletes the branch it created.
- A lock with any other reason is never overridden.
- An undo that still fails says which path and branch it left behind in the
  raised error, not only in a log line.

## Non-Goals

- Finding worktrees earlier runs already left `locked initializing`: a sweep
  for those is a separate follow-up (the issue reports fifteen in one client).
- Changing `Timeout.GIT_WORKTREE`.

## Tasks

### Phase 1: Undo the locked add

- [ ] 🔄 **Task 1.1**: RED tests with a real temporary repo (a worktree locked
  `initializing` is removed and its branch deleted; a worktree locked with another
  reason is left alone and reported; a pre-existing branch is never deleted).
  GREEN: read the lock reason from `worktree list --porcelain`, `worktree unlock`
  when it is `initializing`, then the existing steps. Release note.

## Success Criteria

- [ ] A killed or timed-out add leaves no worktree and no new branch behind.
- [ ] Release-bound consequence recorded as a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- <!-- delivery commit hash -->
