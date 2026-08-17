# Plan 00254: delete-branch must re-check a tip it proved

**Status**: In Progress
**Created**: 2026-08-17
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

`delete-branch` proves each branch safe, writes one recovery bundle for the whole
batch, and then deletes in a loop. Nothing re-reads a branch's tip between the
proof and the delete, so a commit arriving in that window is deleted **silently**:
the proof is stale, and the bundle — written before the loop — does not contain it.

Four of the five tiers use git's force delete, where git checks nothing. Only
`merged` is protected, and only by accident, because `git branch -d` re-runs its
own merged check and refuses. Plan 00253 did not create this: it removed the
accidental cover from one case (`merged-not-in-head`) while fixing a real false
refusal, and `merged-unpushed` has had the same exposure since Plan 00249.

The window is not small. The bundle is written by `git bundle create`, which PACKS
objects — the call carrying a 300 s budget for exactly that reason — so on a large
repository the exposed window is the whole pack, not an instant.

Reported by a peer review session, then re-verified here by execution before
anything was accepted. See [FINDINGS.md](FINDINGS.md) for the reproductions.

## Goals

- No branch is deleted whose tip differs from the one its proof was made against.
- A moved tip produces a REFUSAL naming both shas, not a silent success.
- The recovery bundle's coverage claim becomes true for every tier, rather than for
  the one tier git happens to re-check.
- `git branch -d`'s protection stops being load-bearing by accident.

## Non-Goals

- Not reverting Plan 00253. The false refusal it fixed was real and the dry run
  really was lying; `-d` was only protecting that case by coincidence.
- Not making the window mathematically zero. See Decision 1 — the compare-and-swap
  that would do it costs a guard that fires far more often than this race.
- Not locking the repository or serialising concurrent agents.

## Context & Background

Verified by execution, not inferred (full transcripts in `FINDINGS.md`):

- As shipped, a peer commit landing during the bundle write is lost with
  `refused=False`, `deleted=('done',)`, exit 0, and a bundle path printed as the
  recovery route that does not contain the peer's file.
- The same race on the pre-existing `merged-unpushed` tier loses work identically,
  which is what makes this a latent defect across four tiers rather than a Plan
  00253 regression.
- `git update-ref -d <ref> <expected-sha>` IS a true compare-and-swap.
- But the force delete **refuses a branch checked out in another worktree**, and
  `update-ref -d` deletes it and leaves that worktree with a dangling `HEAD`.
- The force delete also removes `branch.<name>.remote` / `.merge`; `update-ref -d`
  leaves them behind, and those entries are exactly what decides the tier for a
  later branch of the same name.

## Tasks

### Phase 1: Record the tip, and refuse a tip that moved

- [ ] ⬜ **Task 1.1**: RED — a test that advances a branch during the bundle write
  (the real window's widest point) and asserts the branch is NOT deleted and the
  peer's content survives. Must fail against current `main`.
- [ ] ⬜ **Task 1.2**: GREEN — `BranchClassification` gains `tip`, recorded at
  classification for every tier including the refusal paths where it is unknown.
- [ ] ⬜ **Task 1.3**: Re-read `git rev-parse <name>` immediately before each
  delete and refuse THAT branch when it differs from the recorded tip. One rule
  for all five tiers — the invariant is tier-independent.
- [ ] ⬜ **Task 1.4**: Cover the pre-existing exposure too: the same test shape on
  `merged-unpushed`, so the fix is proven where it was never a regression.

### Phase 2: The refusal has to be readable

- [ ] ⬜ **Task 2.1**: The blocker names both shas, says the classification is now
  stale, and says the bundle predates the move so it does NOT cover the new commit.
- [ ] ⬜ **Task 2.2**: Check this reads correctly next to `_REFUSAL_DIAGNOSIS`,
  which says our model disagreed with git. A moved tip is NOT that, so it must not
  borrow that wording.
- [ ] ⬜ **Task 2.3**: Confirm `--format json` reports the same outcome as the text
  path, as Plan 00253 Decision 4 requires of any new refusal shape.

### Phase 3: Verify

- [ ] ⬜ **Task 3.1**: Full QA green, daemon restart RUNNING.
- [ ] ⬜ **Task 3.2**: Re-run both reproductions and confirm each now refuses.
- [ ] ⬜ **Task 3.3**: Confirm the other-worktree guard still fires — the guard
  Decision 1 declines to trade away.

## Dependencies

- Follows: Plan 00253 (Complete), whose review chain surfaced this.
- Distinct from Plan 00252: that is about guards that cannot SEE the data
  (visibility); this is about state changing between read and write (consistency).

## Technical Decisions

### Decision 1: re-read the tip, keep git's own delete

**Context**: the peer proposed `git update-ref -d <ref> <expected-sha>` for the
force tiers, on the grounds that it is atomic and those tiers give up nothing
because git checks nothing there anyway.

**Options Considered**:

1. **Tip re-read, unchanged argv.** One `rev-parse` per branch. Narrows the window
   from a whole bundle pack to a single git invocation. Not airtight.
2. **Compare-and-swap via `update-ref -d`.** Airtight. But executing it showed the
   premise "those tiers give up nothing" is false: the force delete refuses a
   branch checked out in another worktree, and `update-ref -d` deletes it, leaving
   that worktree's `HEAD` dangling. It also leaves `branch.<name>.*` config behind.

**Decision**: Option 1. In this project agents routinely run with
`isolation: "worktree"`, so a branch checked out in a peer's worktree is ordinary,
while the race needs a commit inside one specific window. Option 2 trades a
deterministic guard that fires often for a probabilistic one, and corrupts a peer's
worktree when it fires. This is the second instance of Plan 00253's Decision 1:
the battle-tested tool checks things we did not think to check.

**Date**: 2026-08-17

### Decision 2: one rule, not a per-tier rule

**Context**: only the four force tiers are exposed, so the check could be applied
only to them.

**Decision**: apply it to all five. "Never delete a ref whose value differs from
the one the proof was made against" is tier-independent and needs no reader to
know which tiers force. On `merged` it also replaces git's generic "not fully
merged" with a message naming both shas. A conditional guard is a guard someone
later has to reason about.

**Date**: 2026-08-17

## Success Criteria

- [ ] A commit arriving during the bundle write is never silently deleted
- [ ] Both reproductions (`merged-not-in-head`, `merged-unpushed`) refuse
- [ ] The refusal names both shas and does not reuse the disagreed-with-git wording
- [ ] The other-worktree refusal still fires
- [ ] QA green, daemon restart RUNNING

## Risks & Mitigations

| Risk                                                       | Impact | Probability | Mitigation                                                                              |
| ---------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------------- |
| The residual rev-parse-to-delete window is read as "fixed" | Medium | High        | Task 2.1 states the window honestly in the code and the blocker never implies atomicity |
| Recording `tip` on refusal paths invents a value           | Low    | Medium      | Task 1.2 covers the paths where the branch does not exist; tip stays empty there        |
| A moved tip that is still safe becomes an annoying refusal | Low    | Medium      | Refusing and asking for a reclassify is correct: the proof is stale either way          |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed at the commit that adds this plan.
