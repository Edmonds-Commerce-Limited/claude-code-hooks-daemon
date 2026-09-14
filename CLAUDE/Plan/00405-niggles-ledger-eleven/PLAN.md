# Plan 00405: niggles ledger eleven

**Status**: In Progress
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The open niggles ledger. Small defects get recorded here the turn they are
found, so that noticing something and doing something about it are never the
same decision. Ledger ten
([Plan 00404](../Completed/00404-niggles-ledger-ten/PLAN.md)) is complete, so
this one opens.

An entry is either fixed in place, ruled NOT A DEFECT with the evidence that
settles it, or graduated to its own plan when the fix turns out to be a ruling
rather than an edit.

## Goals

- Every niggle found is written down with the evidence that makes it checkable
  by someone who was not there.
- Each entry reaches a terminal state: fixed, ruled not-a-defect, or graduated.

## Non-Goals

- Fixing anything that needs an owner ruling — that graduates to its own plan.

## Tasks

### Phase 1: Entries

- [x] ✅ **N1**: A pending release callout shipped in a shape no release could
  fold in.

  **Found**: running the wider suite while building
  [Plan 00403](../00403-upstream-issue-reporting-sop/PLAN.md)'s Task 4.1. Both
  faults were in a file committed earlier the same day, and the targeted test
  runs done at the time never touched
  `tests/integration/test_pending_release_notes_holding_area.py`.

  **Evidence.** `42-one-unsecurable-socket-no-longer-costs-them-all.md` carried:

  ```text
  **Plan**: 00404 (N1)
  **Audience**: client projects with `transport.relay_enabled` or `nc_enabled`
  ```

  The holding area enforces `^\*\*Plan\*\*: \d{5}$` and an `**Audience**` drawn
  from a closed set of four. Both lines are helpful prose and neither parses, so
  a release folding this callout in would have failed at the gate — with the
  bug fix itself already tagged and published.

  **Why it is worth an entry rather than a silent fix.** The two faults are the
  same mistake in two fields: a header that a human reads correctly is not a
  header a parser reads at all, and the extra detail that made each line
  *better* to read is exactly what made it unparseable. The fix keeps the
  detail and moves it below the headers, where prose belongs.

  **Fixed** in `6787874f`.

- [x] ✅ **N2**: The plan index's own self-check disagreed with the bullets
  above it.

  **Found**: the same run — `test_repo_hygiene_check` flagged
  `plan-stats-arithmetic` twice against `CLAUDE/Plan/README.md`.

  **Evidence.** The reconciliation bullet stated 394 folders over **391
  distinct** numbers against a counter of **404**, and closed with:

  ```text
  389 + 13 = 402. ✅
  ```

  The check mark is the interesting part. A self-check that carries its own
  tick reads as verified, and the two numbers in it had simply not been
  re-derived when the bullet above them was. Recounted from disk: 22 + 359 + 13
  = 394 folders over 391 distinct numbers, and the 13 folderless numbers the
  bullet lists are exactly the set `comm` produces against the counter — so the
  arithmetic line was the only stale part.

  **Why the checker is right to treat this as detritus.** The figures exist so
  that a future recount can be compared against a stated baseline. A baseline
  that contradicts itself cannot do that job, and the tick makes it look as
  though someone already checked.

  **Fixed** in `6787874f`: `391 + 13 = 404. ✅`.

## Success Criteria

- [ ] ⬜ Every entry above is in a terminal state: fixed, ruled not-a-defect,
  or graduated to its own plan.
- [ ] ⬜ Full QA passes and CI is green.

## Delivery & Milestones

- Opened when ledger ten closed. N1 and N2 were both found by running a wider
  test suite than the change under way needed — neither produced a symptom
  anybody would have hit, and both would have surfaced first at a release.
