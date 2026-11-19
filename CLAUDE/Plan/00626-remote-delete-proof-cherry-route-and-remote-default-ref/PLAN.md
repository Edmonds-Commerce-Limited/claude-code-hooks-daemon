# Plan 00626: remote delete proof cherry route and remote default ref

**Status**: In Progress
**Created**: 2026-11-19
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Two defects in the remote-delete proof (`core/remote_branch_proof.py`), reported from
a client seat whose default branch is not named `main`, both reproduced in scratch
repositories (`untracked/scratch/p626/repro.py`).

**Defect 1 (over-refusal).** `git push origin --delete <branch>` is refused as "not
merged into `<default>`" although `git cherry -v origin/<default> <branch>` marks every
commit `-`: the content commits were cherry-picked onto the default and the branch
then carries a park and an unpark marker. The guard's own rule text allows a delete
whose "patches are all in the default branch (`git cherry`)", but the proof lets the
net-change check alone decide, and that check needs ONE first-parent commit of the
default holding the whole net change. When the default changed one of the branch's
paths between the two cherry-picks, no single commit holds both, so the branch is
refused. Patch-id alone was rejected on purpose (whitespace-insensitive ids, the
no-merge-base case, merges), so the cherry route is restored only with those holes
closed: every commit's patch is in the default (existing `patch_equivalent`, merges
refused), a merge base exists, and every path the branch changes is held at its exact
blob and mode (deletion: absent) by SOME first-parent commit of the default after the
merge base.

**Defect 2 (safety).** The remote proof accepted the LOCAL default branch as a proof
target (ancestry, park-carried, net change and the cache key), so a branch merged only
into an unpushed local default was "proven merged" and its remote copy deletable,
losing work the remote default does not hold. A remote delete must be proven against
the remote's default only: the remote-tracking ref, confirmed equal to the remote's
live default tip in the same `git ls-remote` the proof already makes, failing closed
when either is missing or the listing fails. The proof cache stops authorising a
delete: a remote delete never rests on a cached positive.

## Goals

- The cherry route proves the reported shape (interleaved cherry-picks plus park and
  unpark markers) through the existing proof, not a second implementation.
- Every remote delete decision is proven against the remote default only, with its
  live tip confirmed.
- A forged cache entry cannot authorise a remote delete.

## Non-Goals

- Changing the LOCAL delete proof (`branch_safety.classify_branch`), which is
  reflog-recoverable and already accepts patch equivalence.
- Ledger N671 (issue-report version check reads local release notes): recorded only.

## Tasks

### Phase 1: reproduce

- [x] ✅ **Task 1.1**: Scratch repro of both defects (`untracked/scratch/p626/repro.py`).

### Phase 2: defect 1, the cherry route (TDD)

- [ ] 🔄 **Task 2.1**: RED tests: interleaved cherry-picks plus park markers prove;
  whitespace-only re-application, no merge base, and a branch path the default never
  held at that blob stay refused.
- [ ] ⬜ **Task 2.2**: GREEN: per-path held state in `_net_change_state`, accepted only
  with `patch_equivalent`; bump `PROOF_ALGORITHM_VERSION`.

### Phase 3: defect 2, the remote default only (TDD)

- [ ] ⬜ **Task 3.1**: RED tests: merged only into an unpushed local default is refused;
  stale or locally moved tracking default is refused; missing tracking default refused;
  forged cache entry does not prove.
- [ ] ⬜ **Task 3.2**: GREEN: tracking-only targets, live default check, no cached
  positives on the delete path; keep `branch_creation`'s cache reader keyed alike.
- [ ] ⬜ **Task 3.3**: Audit every remote-delete decision path and record verdicts.

### Phase 4: close-out

- [ ] ⬜ **Task 4.1**: Rule text and docstrings; release note; report.

## Success Criteria

- [ ] Both scratch repros flip (defect 1 proves, defect 2 refuses) and are pinned by tests.
- [ ] Targeted tests pass; no QA suppression.
- [ ] Release note under `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (the pending-release
  holding area) records both fixes.

## Delivery & Milestones

- Report: `subagent-reports/261119-implementation.md`
