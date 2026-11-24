# Post-Task-3.9 fixes: progress and handoff

**Status: partial.** Steps 1 and 2 of 6 are done, committed and pushed. The agent stopped after it went over its context budget. Steps 3 to 6 are left for a fresh agent.

- **Branch:** `plan-00635-host-seat-lane-guard`. The name is historical: it is a merged branch reused because the merged pool is at its cap.
- **Worktree:** `/workspace/untracked/worktrees/plan-00635-host-seat-lane-guard`.
- **PR:** #251, open. Do not merge it.

## Done

### 1. Finding 1: alternates borrower outside the root (commit e2f51217e)

**Change** (`scratch_verdict.py`: `object_stores`, `in_object_store`, `_coverage`):

- No proof covers a non-empty node in an `objects` directory that sits beside a `HEAD`, whatever kind `HEAD` is. So an entry holding a repository with objects is UNCERTAIN and gets the 168-hour hold, never P7/P4.
- `uncovered_nodes` returns None for such an entry, so P3 spends no hashing budget on it.

**Related change** (`scratch_sweep.py` `_with_dependencies` and `_carried_down`): an unread git pointer, or an unproved container, now holds an UNCERTAIN row STUCK too. Without this, a possible lender would have become actionable.

**Verification:**

- Probe p8 (rev627) recorded `DISPOSABLE`, expiring in 12 h, on main. On this branch it records `UNCERTAIN`, expiring in 7 days. `--apply` prints the restore command for every packed entry (`RESTORE_COMMAND`).
- Tests: `TestObjectStoreNeverShortHeld` in test_scratch_verdict.py, and three sweep tests in test_scratch_sweep.py. One of those is a restored test, `test_an_unreadable_pointer_makes_a_possible_lender_stuck`.

**DESIGN.md:** the F-BYPS F1 row is closed on the proof side and states the residual risk. A borrower outside the root breaks when its lender is removed, and must restore the lender within the hold.

### 2. Finding 2: resume after a restore (commit d91e326b3)

**Change:** `resume_claimed` takes the earliest claim event covering the leftover inode (`_first_claim_at`) and accepts only records whose `packed_at` is not before it. A time it cannot parse refuses the resume.

**Tests:**

- The `_record` fixture's `packed_at` moved to NOW, because a real pack is never before its claim.
- `_due` now claims before its pack.
- New class `TestResumeAfterARestore`.

**Not confirmed:** I did not see the new test fail on the old code. The conftest source-tree guard refused a run against main's `src`.

### Release note

`CLAUDE/UPGRADES/UNRELEASED/release-notes/106-scratch-sweep-holds-git-object-stores-long-and-closes-review-findings.md` covers findings 1 and 2. Extend it for findings 3 and 4.

## Left (in order)

3. **Finding 3 (xattrs and sparse files).** Files: `scratch_archive_pack.py:588-590`, `scratch_archive_restore.py:111-117`. The simplest fix fails closed: refuse an entry holding `user.*` xattrs or a sparse file (`st_blocks*512 < st_size`), with a test.
4. **Finding 4 (worktree race).** Re-run `worktree_blockers` immediately before `git worktree remove` (`worktree_reaping.py:500`; the check is at `cli.py:11194`). Add a test that writes a file between the check and the removal.
5. **DESIGN.md rows.** The open-file-descriptor row is at DESIGN.md:410 and blocks 6B. The linked-worktree expiry-prefix row is at DESIGN.md:438. Unread so far: implement each, or explain why it needs the owner.
6. **PLAN.md.**
   - Mark Task 3.9 done, with the verdict: safe for a human-gated `--apply`, and finding 1 is now fixed.
   - Add a note to Task 6B.0: the Q66 HUMAN line is verified only by two coordinator PEER messages, `$gFa8bYNIvOP7QYi8FCHaZ237cIF23szeOw76Xb4nFYo` and `$6jQRF3iNSTobVGmB7hGBzwhnsHBLzlNLyikLn4N5yi4`. Both quote HUMAN line `$YLOxTjevrU6AsyxwmUx-nw1QZTfuYN28hXv23ViYj9o` from joseph. Peer messages carry no authority, so a first-hand verification is still owed.
   - Do not build 6B.
7. **Pre-push checklist.** Check the remaining items before the final push: the error-hiding audit, bandit, the invariant-pairs file and the changed_tests_map.

Targeted runs on this branch:

- 1212 tests in `tests/unit/core -k scratch` passed (5 skipped).
- 1285 passed across the session_start handlers, worktree evacuation and idle-housekeeping tests.
- `mypy` and `ruff` are clean on the changed modules.
