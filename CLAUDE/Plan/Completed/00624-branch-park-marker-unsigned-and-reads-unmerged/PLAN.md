# Plan 00624: branch park marker unsigned and reads unmerged

**Status**: Complete
**Created**: 2026-11-19
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded
**GitHub Issue**: #210, #211

## Overview

Issue #210: `branch-park` wrote its park/unpark marker with plain `git commit-tree`,
ignoring `commit.gpgsign`, so a parked branch could not land on a branch whose forge
requires signed commits. Issue #211: the merged/deletable judgements counted those
empty marker commits as unmerged work, so a parked branch whose real commits were on
the default branch never read as merged.

Both were reported against 3.74.0. Phase 1 reproduced each issue on current main
(scratch repos under `untracked/scratch/00624/`). Outcome: both were already fixed in
v3.75.0 (#210 by commit `d2e73d0e9`; #211 by Plans 00594 and 00622) and are closed.
Findings are in `subagent-reports/repro-findings.md`.

Phase 2 (record a park under `refs/parked/<name>` so the branch gets no marker commit)
was a coordinator's suggestion, not an owner request. The owner wants no drift into new
features, so Phase 2 is NOT built and is closed as not needed.
[DESIGN-ref-park.md](DESIGN-ref-park.md) stays as a record only and is marked not adopted.

## Goals

- Prove on current main which issue paths are already fixed. Done.

## Non-Goals

- Phase 2 (ref-based park): not adopted, see above.
- Rewriting history of already-parked branches to drop old markers.
- Loosening the worktree reaper (it stays deliberately conservative; see report).

## Tasks

### Phase 1: establish what is already fixed

- [x] ✅ **Task 1.1**: reproduce #210 and #211 on main in scratch repos
- [x] ✅ **Task 1.2**: closed as not needed: the existing tests
  (`tests/unit/core/test_branch_park_signing.py`,
  `tests/integration/test_branch_park_signed_commits_e2e.py`, and the Plan 00594, 00617
  and 00622 tests) already cover the fixed paths and the refusal cases

### Phase 2: park without a branch commit (not adopted)

- [x] ✅ **Task 2.1 to 2.4**: closed as not needed (design not adopted, nothing built)

### Phase 3: ship

- [x] ✅ **Task 3.1**: closed as not needed (no source change, so no release note or docs)
- [x] ✅ **Task 3.2**: closed as not needed (docs-only change)

## Success Criteria

- [x] Every repro scenario in the findings report passes on main and the refusal
  scenarios are still refused (`subagent-reports/repro-findings.md`)
- [x] Issues #210 and #211 are closed, fixed in v3.75.0
- [x] Holding area: no release-bound consequences. No source code changed (plan files
  only), so there is no release note to add to `CLAUDE/UPGRADES/UNRELEASED/`

## Delivery & Milestones

- Plan filed: `3d9d89547`
- Closed as already fixed; Phase 2 not adopted; archived to `Completed/`
