# Plan 00618: release 3 75 0 code review findings

**Status**: Not Started
**Created**: 2026-11-16
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The Step 10 code review of release 3.75.0 (`subagent-reports/261116-step10-code-review.md`) returned FAIL with 38 findings against `git diff v3.74.0..HEAD -- src/`: 5 blocking, 20 non-blocking defects and 13 nits. The release was aborted at that gate, as RELEASING.md requires, with no merge, tag or publish. The release branch `release/3.75.0` is kept for the re-run.

A release carries no known defect, and deferring one needs the human's explicit acceptance. The five blocking findings are all fail-open or data-loss paths introduced since the last release, so they are fixed first, test-first, with no loosening of any guard. The remaining defects are triaged: each is fixed or recorded as accepted by the owner.

## Goals

- Each blocking finding is fixed test-first, with a red test committed before the fix: B-1 (delete-branch content proof can delete unpushed work and no recovery copy exists), B-2 (the stop guard hands over any worktree under the harness directory or any locked one without a liveness check), B-3 and B-4 (the new git search-option exemption lets `git grep -G <protected>` and `git blame -S <protected>` read a protected file), B-5 (the grep/rg check skips the first searched directory when the pattern is written `-ezz` or `--regexp=zz`).
- Every non-blocking defect is fixed or has an explicit owner decision recorded.
- The nits are fixed where trivial in the touched code.
- Each fix is independently reviewed for loosening before merge.

## Non-Goals

- Re-cutting the release (the owner starts that with `/release`).
- Implementing Plan 00614, 00615 or 00617 (separate plans).

## Tasks

### Phase 1: Blocking findings

- [ ] ⬜ **Task 1.1**: B-1, delete-branch content-preserved proof (use the per-path net-change proof or drop the tier), with the reviewer's reproduction as the red test.
- [ ] ⬜ **Task 1.2**: B-2, stop guard handover requires proof a live agent owns the worktree, and never drops a branch in the session's own set.
- [ ] ⬜ **Task 1.3**: B-3 and B-4, the git search-option exemption applies only to the subcommands where the option takes a value; `git grep -G` and `git blame -S` stay denied for protected files.
- [ ] ⬜ **Task 1.4**: B-5, the grep/rg first-searched-directory check handles `-e<pattern>` and `--regexp=<pattern>` spellings.

### Phase 2: Non-blocking defects and nits

- [ ] ⬜ **Task 2.1**: Triage the 20 non-blocking defects in the report: fix each test-first, or record the owner's explicit acceptance.
- [ ] ⬜ **Task 2.2**: Fix the nits in the code touched by Tasks 1.x and 2.1.

### Phase 3: Hand-off

- [ ] ⬜ **Task 3.1**: Independent loosening review of Phase 1 and 2, CI green on main, a release note, then tell the owner the release can be re-run.

## Success Criteria

- [ ] All five blocking findings are fixed, each with a test that failed before the fix.
- [ ] No fix makes a guard allow anything it denied on the previous commit.
- [ ] The non-blocking defects are each fixed or explicitly accepted by the owner.
- [ ] A release note is added under `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (the holding-area artefact for this plan).

## Delivery & Milestones

- Filed after the 3.75.0 release was aborted at Step 10; nothing delivered yet.
