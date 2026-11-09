# Plan 00579: copy seeded files and worktree removal

**Status**: Not Started
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

A related issue filed the same day: #173 (`WorktreeCreate` cleanup cannot remove a worktree git left locked
"initializing"). #167 (an `optional: true` seed entry reported as missing) does not interact with this one, and is fixed
on its own by Plan 00580.

## Owner rulings (2026-11-09)

- **Q1, yes.** A worktree holding only seeded copies is of course fine to remove: a seeded copy cannot be lost, since
  its source is in the main checkout. Confirm it has not diverged from that source; any difference might be work lost
  by accident, so a diverged copy still blocks and is named in the deny.
- **Q2, yes (follows from Q1).** The guard reads the `worktree_create` seed list directly, so no path is listed twice;
  `regenerable` still adds to it.
- **Q3, no.** #173 is a separate issue and goes through the issue loop on its own.

## Goals

- The worktree-removal check treats a copy-mode seeded file as not losable while it is byte-identical to its source
  in the main checkout, read from the seed list itself.
- A diverged seeded copy blocks the removal, and the deny names it and says it differs from its source.
- Symlink-mode seeds, `regenerable` globs and every other ignored entry behave as before.

## Non-Goals

- #173 (a worktree git left locked "initializing").
- No change to how seeds are created.

## Tasks

### Phase 1: Fix

- [ ] ⬜ **Task 1.1**: RED tests in real temporary repositories: a merged clean worktree whose only leftover is an
  identical seeded copy is removable; the same with a diverged copy is denied and names the file; a missing source
  counts as diverged
- [ ] ⬜ **Task 1.2**: GREEN in `core/branch_cleanup.py` (and wherever the removal judge lists unregenerable ignored
  entries), reading the seed entries through the existing seed-list loader
- [ ] ⬜ **Task 1.3**: release-notes callout

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: targeted QA, merge, verify CI, close #164

## Success Criteria

- [ ] The new tests failed before the fix and pass after it, in every direction above
- [ ] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
- [ ] Merged to main with green CI; #164 closed

## Delivery & Milestones

- (pending)
