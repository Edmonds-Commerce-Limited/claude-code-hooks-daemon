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
- The force delete **refuses a branch checked out in another worktree**;
  `update-ref -d` with a matching sha deletes it and leaves that worktree with a
  dangling `HEAD`. This needs stating precisely, because a first pass overstated
  it: `classify_branch` ALREADY refuses that case itself (`REFUSAL_WORKTREE`), so
  in the ordinary path the switch would lose nothing. What it would lose is the
  RACING case — a peer that checks out the branch after classification, which
  moves no tip and so is invisible to any tip re-check, while git's delete-time
  check still refuses it. Verified through the real engine.
- The force delete also removes `branch.<name>.remote` / `.merge`; `update-ref -d`
  leaves them behind, and those entries are exactly what decides the tier for a
  later branch of the same name.

## Tasks

### Phase 1: Record the tip, and refuse a tip that moved

- [x] ✅ **Task 1.1**: RED — 4 of the 5 new tests failed against `main`, on both the
  new tier and the pre-existing one. The 5th (wording) could not be RED: with no
  blockers at all the assertion was trivially true, and its docstring records that.
- [x] ✅ **Task 1.2**: GREEN — `BranchClassification.tip`, read once after the
  refusal checks (branch known to resolve) and before any proof is computed, so
  every tier reports the sha it actually reasoned about. Empty on refusal paths.
- [x] ✅ **Task 1.3**: `tip_moved_since_proof` runs for every classification at the
  top of the delete loop and appends a blocker instead of deleting.
- [x] ✅ **Task 1.4**: `merged-unpushed` covered by the same test shape and refused.

### Phase 2: The refusal has to be readable

- [x] ✅ **Task 2.1**: Verified by executing the real engine, not just the unit test:
  `classified against bc4a396, now at 8d5bb91`, then the bundle gap, "Nothing was
  deleted for this branch", re-run to reclassify, and do not force past it.
- [x] ✅ **Task 2.2**: `_MOVED_TIP_DIAGNOSIS` is a separate constant and the
  predicate-gap wording is asserted absent — a moved tip is a concurrent edit, so
  sending the reader to inspect the predicate would misdirect them.
- [x] ✅ **Task 2.3**: Text says `PARTIALLY REFUSED … quiet` and JSON reports
  `refused=true, deleted=["quiet"]` with the same blocker; both exit 1. This also
  restores a NATURAL reproduction of Plan 00253's partial-batch rendering, which
  that plan had recorded as unreachable after its own fix.

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
2. **Compare-and-swap via `update-ref -d`.** Airtight against a moved tip. But
   executing it showed the premise "those tiers give up nothing" is false, though
   not for the reason a first pass claimed. `classify_branch` already refuses a
   branch checked out in a linked worktree, so the ordinary case is covered before
   the delete is reached. The loss is confined to the racing case, which is the
   whole subject of this plan: a peer that checks out the branch AFTER
   classification does not move the tip, so no tip re-check can see it, while
   git's delete-time check still refuses — and `update-ref -d` with the matching
   sha would delete the ref and leave the peer's worktree with a dangling `HEAD`.
   It also leaves `branch.<name>.*` config behind.

**Decision**: Option 1. The two options are not "atomic versus not" but "which
delete-time checks do we keep". Option 2 closes the moved-tip window and opens a
checked-out-by-a-peer one, and in a project where agents routinely run with
`isolation: "worktree"` that second window is not the cheaper one to open. Keeping
git's delete means every delete-time check it makes survives the race, including
the ones nobody here enumerated.

This is the second instance of Plan 00253's Decision 1, and the pair is worth
reading together: there the argument was to trust git's predicate over ours, here
it is to trust git's delete over a proposed replacement for it.

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
