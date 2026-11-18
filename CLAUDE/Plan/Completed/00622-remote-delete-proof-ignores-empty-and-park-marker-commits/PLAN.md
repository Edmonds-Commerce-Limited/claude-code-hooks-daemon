# Plan 00622: remote delete proof ignores empty and park marker commits

**Status**: Complete
**Created**: 2026-11-18
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A client upgrading to 3.75.0 reports that `R-GIT-PUSH-DELETE-REMOTE` refuses to delete remote branches whose content is
already in the default branch, saying "not merged". Each such branch carries an empty "Unpark branch" commit pushed on
top of the otherwise merged work. An empty commit has no patch id, so a patch-by-patch comparison (`git cherry`) can
report it as unmerged, and it may also defeat the net-change check. This is a peer report: it has not been reproduced
here yet, and the first task is to reproduce it.

The fix must only ever make the proof recognise commits that carry no content: an empty commit (its tree equals its
parent's tree), and the daemon's own park and unpark marker commits. It must never loosen the proof for any branch whose
content is not in the default branch. This is data-loss-adjacent, so it needs security-grade review.

## Goals

- A branch whose every non-empty change is already in the default branch, plus empty or marker-only commits, passes the
  remote-delete proof and the local delete-branch proof.
- No branch carrying content outside the default branch gains a pass.

## Non-Goals

- A route for removing work that is deliberately not in the default branch. That is Plan 00620.

## Tasks

### Phase 1: Reproduce

- [x] ✅ **Task 1.1**: Build the reported shapes as synthetic repositories and show the current proof refuses them. RED
  tests. Shapes: (a) content merged, an empty unpark commit on top; (b) a park marker commit; (c) the case the peer
  measured on one branch, where `git cherry` also marks two CONTENT commits unmerged because the default branch merged a
  modified version of them (a pull request that changed the patch). Which proof applies depends on the path: the REMOTE
  proof (`core/remote_branch_proof.py`) is decided by net change alone (`holds_net_change`), and `git cherry` only names
  the tier afterwards, so there is no separate cherry route to pass; the LOCAL proof (`daemon/branch_safety.py`) needs
  file survival AND net change together in its content-preserved tier. Skipping empty commits alone is necessary but
  not sufficient for shape (c); establish by test what each path decides for it and record the expected outcome, rather
  than assuming it passes.

### Phase 2: Fix (test first)

- [x] ✅ **Task 2.1**: Ignore commits whose tree equals their parent's tree, and the daemon's own park marker commits, in
  the proof, in `daemon/branch_safety.py` and `core/remote_branch_proof.py`.
- [x] ✅ **Task 2.2**: A corpus check showing 0 DENY to ALLOW changes for every branch shape that carries real content,
  including a content-bearing commit that happens to be named like a marker.
- [x] ✅ **Task 2.3**: Independent loosening review (Opus), release note, handler guidance. Evidence: three review rounds
  (`subagent-reports/261118-loosening-review.md`, `-2.md`, `-3.md`), each a FAIL verdict. Round 1 (2 defects) was fixed
  in round 2 (`43fb88b57`) and round 2 (2 Low defects) in round 3 (`164ba4986`, `e1c121abe`); round 3's two Low
  defects (a hand-forged loose commit object, and a walk that exits 0 without the tip line) are not fixed here and are
  ledgered as N665 and N666 in `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md`; a whitespace-only older hole
  is ledgered as N660. Release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/002-empty-commits-no-longer-block-branch-deletes.md` exists. Handler
  guidance: no change needed, because the generated rule text (`R-GIT-PUSH-DELETE-REMOTE`: a branch not merged into
  the default) stays true; the new `empty-commits-only` tier is documented in the release note and the module docstrings.

## Success Criteria

- [x] The reported shapes pass the proof and the RED tests were committed first (RED commits `0fff8d932`, `ca5ba5d35`;
  GREEN `a9bb1177d`, `43fb88b57`, `164ba4986`; merged at `eba1de61f`; non-test QA gate 44/44).
- [x] The corpus check shows 0 DENY to ALLOW changes for content-bearing branches (`corpus/`, re-run after round 2).
  The three independent reviews returned FAIL: rounds 1 and 2 were fixed, and round 3's two Low items are ledgered N665
  and N666 (neither reachable with ordinary git commands).
- [x] The release-bound consequences are recorded in the pending-release holding area: release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/002-empty-commits-no-longer-block-branch-deletes.md`.

## Delivery & Milestones

- Filed from a client report; the reproduction comes first.
