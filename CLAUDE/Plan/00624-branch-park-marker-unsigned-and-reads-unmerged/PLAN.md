# Plan 00624: branch park marker unsigned and reads unmerged

**Status**: In Progress
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

Both were reported against 3.74.0. The first step of this plan reproduces each issue
on current main (scratch repos under `untracked/scratch/00624/`) and fixes only what
still fails. Findings are in `subagent-reports/repro-findings.md`.

The remaining design goal (owner ruling): a park should not add a commit to the branch
at all, so the tip stays real work. The park marker is written as now (same trailers,
signed when `commit.gpgsign` is true) but recorded under `refs/parked/<name>` and
pushed there, instead of moving the branch. A park stands while the marker's parent is
the branch tip. Old on-branch markers stay readable (compat).

## Goals

- Prove on current main which issue paths are already fixed; regression-test them.
- A new park leaves the branch tip untouched; the park is shared through
  `refs/parked/<name>` on the remote.
- Every reader (pools, ages, reasons, `--clear`, ladder, stop guard) sees ref parks.
- Old on-branch marker parks stay readable and clearable (the unpark marker is signed).
- No merged/deletable proof ever accepts a branch because of a park ref.

## Non-Goals

- Rewriting history of already-parked branches to drop old markers.
- Loosening the worktree reaper (it stays deliberately conservative; see report).

## Tasks

### Phase 1: establish what is already fixed

- [x] ✅ **Task 1.1**: reproduce #210 and #211 on main in scratch repos
- [ ] 🔄 **Task 1.2**: characterisation tests for the fixed paths plus refusal cases
  (real commit on top of a park, a park-message commit that changes a file)

### Phase 2: park without a branch commit

- [ ] ⬜ **Task 2.1**: RED tests: park leaves tip, writes signed `refs/parked/<name>`,
  pushes it; readers see it; clear deletes it; legacy markers still read and clear
- [ ] ⬜ **Task 2.2**: GREEN: `branch_park` writer and `read_park_records` reader
- [ ] ⬜ **Task 2.3**: inventory / creation-guard overlay for remote-only ref parks
- [ ] ⬜ **Task 2.4**: session-start fetch of `refs/parked/*`

### Phase 3: ship

- [ ] ⬜ **Task 3.1**: release note, CLI help, docs
- [ ] ⬜ **Task 3.2**: independent review, then hand to the coordinator

## Success Criteria

- [ ] Every repro scenario in the findings report passes on the branch and the
  refusal scenarios are still refused
- [ ] A park made by this branch leaves `refs/heads/<name>` unchanged
- [ ] Release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (the holding area)
- [ ] Targeted tests green; full gate run by the coordinator

## Delivery & Milestones

- Plan filed: `3d9d89547`
