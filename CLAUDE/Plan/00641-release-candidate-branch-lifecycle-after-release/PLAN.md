# Plan 00641: release candidate branch lifecycle after release

**Status**: Not Started
**Created**: 2026-11-25
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Found on 25 Nov by the hooks-daemon seat of the lts-ops team, and named as a process defect by the owner ("why are we keeping release branches when they are already released? ... implies something fundamentally wrong with hooks daemon processes"). Two release-candidate branches, `origin/rc/3.73.3` and `origin/rc/3.74.0`, stayed on the remote after their releases. `bin/hooks-daemon branch-sweep --clean --remote` skipped them with the notes "kept: previous rc kept while client seats may still track it" and "kept: client seats still run this rc until the prod cut-over". `branch-preflight` meanwhile counted both as merged and stale ("neither deleted nor kept") and refused every new branch (R-BRANCH-MERGED-POOL). They were deleted on 25 Nov with `bin/hooks-daemon delete-branch --remote-only`, whose proof was "merged into the default branch"; the restore line for each was printed and reported to the coordinator.

What was checked, and what was not:

- `CLAUDE/development/RELEASING.md` describes an RC (cut, pre-push checks, announcing, installing on a client seat, following a moved RC). In the lines read and by a search for retire, delete and "after the release", it names no step that retires an RC branch once its release is tagged. That is the gap, as far as read; Task 1.2 reads the whole document.
- The "client seats may still track it" notes: no record backing them was found in the repository's configuration or in the code searched (`core/`, `daemon/`, `.claude/hooks-daemon.yaml`, `git config --local`). Where the sweep reads them from is not established (Task 1.1).
- A keep and a sweep skip are not the same thing: the pool counted the branches as unkept while the sweep refused to delete them, so the only exits were a human or a `keep` record nobody had written.

## Goals

- A release's own procedure says what happens to its RC branch, and does it, or states who does and when.
- A branch that is kept has a recorded reason and an end date that the pool and the sweep both read, so "kept" means the same thing to both.
- The sweep never skips a branch on a note that no record backs.

## Non-Goals

- Deciding which client seats still need an old RC: that is the owner's call, recorded per branch, never assumed.
- Changing the merged-pool cap or its other rules.

## Tasks

### Phase 1: Establish the facts

- [ ] ⬜ **Task 1.1**: Find where `branch-sweep` gets the "kept: ..." notes it printed for the two RC branches (code, config, state files) and record the answer in the JOURNAL.
- [ ] ⬜ **Task 1.2**: Read `CLAUDE/development/RELEASING.md` start to end and confirm or refute that no step retires the RC after its release; record each place RCs are named.

### Phase 2: Fix, test first

- [ ] ⬜ **Task 2.1**: Add the post-release step for the RC branch to the release procedure (and to the `/release` skill if it drives that procedure), with the restore line recorded.
- [ ] ⬜ **Task 2.2**: Make a keep a recorded fact with a reason and an expiry, read by both `branch-preflight` and `branch-sweep`; a sweep skip with no such record is reported as a defect, not honoured.
- [ ] ⬜ **Task 2.3**: Tests for 2.2 written first and shown failing; restart the daemon and verify live; targeted QA.

## Success Criteria

- [ ] The Task 1.1 and 1.2 answers are in the JOURNAL.
- [ ] The release procedure retires its RC branch or names the actor.
- [ ] A branch the sweep skips is always a branch with a recorded keep; the pool and the sweep agree.
- [ ] Release-bound consequences recorded in the pending-release holding area as a release note.

## Delivery & Milestones

- Plan filed by seat 5 (lts-ops); no delivery commit yet.
