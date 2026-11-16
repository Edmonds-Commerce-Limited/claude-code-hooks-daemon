# Plan 00617: park commit keeps merged branch deletable

**Status**: Not Started
**Created**: 2026-11-16
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Parking a branch writes a park record as a commit on the branch. When the
branch's real work is already merged into the default branch, the only commits
left on it are those empty (tree-identical) park commits. The branch guard then
counts the branch as unmerged, so `branch-sweep --clean --remote` refuses to
delete it and `R-GIT-PUSH-DELETE-REMOTE` refuses a remote delete. A finished
branch becomes something only a human can delete, the merged pool sits at its
cap and `R-BRANCH-MERGED-POOL` then blocks every new agent branch.

A peer team reported nine remote branches in this state, each with an empty
`git diff <default>...<branch>`. The owner's view: if a human has to clear
this, the tool is wrong. The fix belongs in the daemon, test first, failing
closed: a branch is deletable as merged only when everything it carries that
the default branch lacks is provably content-free.

## Goals

- A branch whose every commit not on the default branch is an empty park commit
  (tree equal to its first parent, and written by the park writer) is classified
  merged by `branch-sweep`, by the delete-branch guard and by
  `R-GIT-PUSH-DELETE-REMOTE`, and is deletable behind the recovery bundle.
- A branch carrying any commit with a tree change, or any commit not provably a
  park commit, is still classified unmerged (the narrowing is proven by a test
  for each such twin, including a park-looking commit that changes a file).
- Decide, with evidence, whether the park record should live somewhere other
  than a commit on the branch (a ref, a note or a file under the daemon's state
  directory), so parking never changes what the branch is.

## Non-Goals

- Deleting any branch by hand or with a force flag.
- Loosening what counts as merged for branches with real content.
- Changing the parked pool cap or the park age limits.

## Tasks

### Phase 1: Reproduce and decide

- [ ] ⬜ **Task 1.1**: Reproduce on a synthetic repository: merge a branch, park it, add the empty park commit, then run `branch-sweep --clean --remote` and the remote-delete guard; record each verdict.
- [ ] ⬜ **Task 1.2**: Write the decision: classify park-only branches as merged, or move the park record off the branch, or both. Record the trade-offs (existing parked branches already carry park commits, so the classifier is needed either way).

### Phase 2: Fix, test first

- [ ] ⬜ **Task 2.1**: RED tests for the classifier: park-only branch is merged; a park commit that changes a file is unmerged; a branch with one real commit under park commits is unmerged; a forged park-looking message on a non-empty commit is unmerged.
- [ ] ⬜ **Task 2.2**: Implement the shared classifier once and use it in `branch-sweep`, the delete-branch guard and `R-GIT-PUSH-DELETE-REMOTE`, so the three cannot disagree.
- [ ] ⬜ **Task 2.3**: If Task 1.2 moves the record off the branch, migrate existing park records and keep reading the old form.

### Phase 3: Release hand-off

- [ ] ⬜ **Task 3.1**: Add a release note and tell the requesting peer team the plan number and, once landed, the release.

## Success Criteria

- [ ] The reproduction from Task 1.1 ends with the park-only branch deletable by the guards, with no human step.
- [ ] Every unmerged twin from Task 2.1 is still refused.
- [ ] A release note is added under `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (the holding-area artefact for this plan).

## Delivery & Milestones

- Filed from a peer report; nothing delivered yet.
