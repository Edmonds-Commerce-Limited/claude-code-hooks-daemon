# Plan 00641: release candidate branch lifecycle after release

**Status**: In Progress
**Created**: 2026-11-25
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Found on 25 Nov by the hooks-daemon seat of the lts-ops team, and named as a process defect by the owner ("why are we keeping release branches when they are already released? ... implies something fundamentally wrong with hooks daemon processes"). Two release-candidate branches, `origin/rc/3.73.3` (tip `6b3930d62d1c`) and `origin/rc/3.74.0` (tip `8f00c69c81f8`), stayed on the remote after their releases. `bin/hooks-daemon branch-sweep --clean --remote` skipped them with the notes "kept: previous rc kept while client seats may still track it" and "kept: client seats still run this rc until the prod cut-over". `branch-preflight` meanwhile counted both as merged and stale ("neither deleted nor kept") and refused every new branch (R-BRANCH-MERGED-POOL). They were deleted on 25 Nov with `bin/hooks-daemon delete-branch --remote-only`, whose proof was "merged into the default branch"; the restore line for each was printed. The owner's answer to the team's question about them (relayed by the coordinator, not verified from this seat) was to remove them.

What was checked (an independent reviewer of this plan's first draft corrected two claims, both fixed here):

- **The keep records exist.** Both branches had a `branch-keep` record as a git note, visible here under `refs/notes/hooks-daemon-remote/origin/keep` and written 2026-11-11 by the owner: "previous rc kept while client seats may still track it" on `6b3930d62d1c` and "client seats still run this rc until the prod cut-over" on `8f00c69c81f8`. The sweep honoured them (its skip lines print exactly those reasons). The first draft of this plan missed them because the search covered configuration and code, not notes refs.
- **The defect is a disagreement, not a missing record.** The sweep treated the keeps as live while `branch-preflight` counted the same branches as "neither deleted nor kept" and blocked branch creation on them. The cause is not yet established: the reviewer's untested guess is that preflight does not read the fetched notes, or runs out of time budget before it does (Task 1.1). The records also say nothing about when "until the prod cut-over" ends, so nothing ever ended the keep.
- **The release document does say what happens to an RC, in prose.** `CLAUDE/development/RELEASING.md` "Ending an RC" says that once the tag is published every RC seat is told to return to stable and the RC branch is deleted. It names no numbered step that does this: the release's final branch step deletes only `release/X.Y.Z`, the housekeeping step does not mention RCs, and the `/release` skill does not mention them (Task 1.2 confirms each).

## Goals

- The release procedure has a numbered step that retires the released RC branch (or records a dated, reasoned keep), so the prose rule is actually carried out.
- `branch-preflight` and `branch-sweep` give the same answer for the same keep record, including whether it has lapsed.
- A keep that names an event ("until the prod cut-over") also records a date or condition that ends it.

## Non-Goals

- Deciding which client seats still need an old RC: that is the owner's call, recorded per branch, never assumed.
- Building a second keep mechanism: the existing `branch-keep` records are the mechanism; this plan makes the commands agree about them.
- Changing the merged-pool cap or its other rules.

## Tasks

### Phase 1: Establish the facts

- [x] ✅ **Task 1.1**: Reproduce the disagreement: with a merged branch that carries an unexpired `branch-keep` note, run `branch-sweep --clean --remote` and `branch-preflight` and record both outputs. Find why preflight counts it as unkept (notes not fetched or read, or a time budget) and record the cause in the JOURNAL.
- [x] ✅ **Task 1.2**: Read `CLAUDE/development/RELEASING.md` start to end, and the `/release` skill, and record each place RCs are named and which step, if any, retires one.

### Phase 2: Fix, test first

- [x] ✅ **Task 2.1**: Test first, then fix: `branch-preflight` and `branch-sweep` agree on a keep record (live, lapsed, absent).
- [x] ✅ **Task 2.2**: Add the numbered post-release step that retires the RC branch (or records a dated keep with a reason) to the release procedure and to the `/release` skill if it drives that procedure; the step prints the restore line.
- [ ] ⬜ **Task 2.3**: Restart the daemon and verify live; run targeted QA. (Daemon restarted; live `branch-preflight` still refuses on three unkept merged branches, which is correct since none has a keep. Ticked at completion, after the merge.)

## Success Criteria

- [ ] The Task 1.1 and 1.2 answers are in the JOURNAL.
- [ ] The two commands agree on every keep state (live, lapsed, absent), shown by tests in `tests/unit/daemon/test_cli_branch_preflight.py` that failed first.
- [ ] The release procedure retires its RC branch in a numbered step (Step 15.2 of `CLAUDE/development/RELEASING.md`).
- [ ] Release-bound consequences recorded in the pending-release holding area as release note 109 under `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- Plan filed by seat 5 (lts-ops); corrected after an independent review.
- Delivery: branch `fix-rc-branch-keep-agreement`. `clean_sweep` clears the stale mark of every branch it sees as kept, by branch name; Step 15.2 of RELEASING.md retires the released RC; release note 109 holds the operator-facing consequence. Independent review approved, with two findings applied (clear by name, add the lapsed-keep test).
