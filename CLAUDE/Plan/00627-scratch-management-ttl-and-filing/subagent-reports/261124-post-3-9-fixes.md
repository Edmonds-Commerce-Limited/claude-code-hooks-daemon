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

## Continuation (second agent): step 3 done, stopped at the context budget

### 3. Finding 3: xattrs and sparse files (commit a295d2a99)

**Change:** the step takes the fail-closed route.

- `walk_tree` (`scratch_archive_claim.py`) records two things on every `Node`:
  - `user_xattrs`: the `user.*` names, read through the procfs link of the verified directory descriptor (`PROC_FD_PARTS`, now shared with pack).
  - `sparse`: `st_blocks*512 < st_size` is only a pre-filter. The file is then opened `O_NOFOLLOW`, its inode is checked, and `SEEK_HOLE` decides, so a compressing filesystem does not refuse everything. ENOTSUP counts as no xattrs. Any other failure gives `None`, meaning unknown.
- The new `refuse_unrestorable` (pack) runs the owner check and refuses an entry if any node has a user xattr, a hole, or an unknown value. It replaces `refuse_foreign_owner` in pack, apply (the pre-claim check), adopt and remove (the check before removal). Batch `_loose_node` now calls it too; until now batch had no owner check either.
- Evacuation still calls only `refuse_foreign_owner`. Evacuation moves the entry, and the pack that follows refuses it.

**Tests:**

- `TestWalkProbesWhatTarCannotCarry` (claim): 9 tests. The xattr test uses a real `setxattr` on this host.
- A parametrised refusal test, plus `test_a_real_sparse_file_is_refused` (pack).
- `test_a_sparse_loose_file_is_refused` (batch).
- **RED first:** all 15 new tests failed on the old code before the fix. The real sparse pack and batch tests failed with DID NOT RAISE, which confirms the finding.
- **GREEN:** the 271 tests across the claim, pack and batch tests and `tests/unit/qa/test_audit_error_hiding.py` pass. A run of `tests/unit/core -k 'scratch or evacuation or worktree'` gave 1579 passed and 1 failed. The failure is in `test_branch_inventory`, which is unrelated: a different test of it fails on each run.

**Checks:**

- `black`, `ruff`, `mypy` and `bandit` are clean.
- A cold import of `scratch_archive_batch` works.

**Other files:**

- Two function-keyed exclusions in `scripts/qa/error_hiding_exclusions.json`: `_user_xattrs` and `_sparse`, both returning None on error, which fails closed.
- Release note 106 is extended to cover this.

**Not done:** POSIX ACLs (`system.posix_acl_*`) and `security.capability` are lost the same way. They are not refused and need a NIGGLES.md entry. This agent did not write it.

### Left for the next agent

Steps 4, 5 and 6, then the PR #251 body, as listed above.

- **Step 4:** advisor guidance is to put the re-check inside `worktree_reaping.py`, directly before the remove call, so every caller gets it. First confirm that `worktree_blockers` sees a new *ignored* file under `untracked/`. Then state in DESIGN.md and the release note that the re-check narrows the window but does not close it.
- **Step 6:** add the note that step 2's resume test was never seen failing against the old code.
- **Trailer:** the task asked for `Claude Sonnet 5.5`, but the harness attribution reminder says `Claude Opus 5.5` and yields only to the user's own instructions. Commit a295d2a99 uses Opus.

## Continuation (third agent): steps 4 and 5a done, stopped past the context budget

### 4. Finding 4: worktree race (commit 24399b596)

- `reap_worktree` takes a REQUIRED keyword `blockers_fn` and reads it as the last step before `git worktree remove`. A blocker returns `ReapOutcome(blocked=True)`; `cmd_worktree_reap` prints `KEEP` and counts it refused. The cli passes its `blockers_of`.
- Tests: `TestTheBlockersAreReadAgainJustBeforeTheRemoval` (unit, 5) and `test_a_note_written_after_the_blockers_check_is_not_deleted` (real git). The real-git test was seen RED (note deleted) with the cli call temporarily passing a no-blockers callable, then GREEN.
- DESIGN.md row and release note 106 say it NARROWS the window, not closes it. Other `worktree_blockers` callers (`branch_cleanup.py` 1007/1195, the WorktreeRemove handler) unchanged: worth one NIGGLES line.

### 5a. Open-descriptor row (this commit)

- `read_process_cwds` now fills `ProcessCwdReading.open_paths` from `/proc/<pid>/fd` links and `/proc/<pid>/maps`; an unreadable table or map makes the pid unreadable (every entry live); a missing one means exited. `entry_in_use` checks open paths under `<name>` and `.sweeping-<name>`.
- Tests: `TestReadOpenFiles` (8, incl. one on the real `/proc`) and two in `test_scratch_archive_facts.py`; 11 seen RED first. 1523 passed across core/daemon scratch, liveness and evacuation, plus the error-hiding audit. black, ruff, mypy clean.
- DESIGN.md: a new closed row above the old one; the old row is retitled "Analysis (closed by the row above)". Residual stated: a descriptor opened after the last re-check; the classification pass still reads cwds only.

### Left for the next agent

- **5b.** DESIGN.md row "a worktree root and the main root share the original-path prefix `untracked/scratch`" (~line 440): NOT touched. Either implement (a linked-worktree `--apply` must not run `_expire` against the shared prefix, e.g. set `expire=False` when the root is in a linked worktree, test-first) or write the owner question into the row.
- **6.** PLAN.md: Task 3.9 done with verdict (Phases 1-3 safe for human-gated `--apply`; findings 1-4 fixed in PR 251); Task 6B.0 Q66 note (peer messages `$gFa8bYNIvOP7QYi8FCHaZ237cIF23szeOw76Xb4nFYo`, `$6jQRF3iNSTobVGmB7hGBzwhnsHBLzlNLyikLn4N5yi4` quoting HUMAN line `$YLOxTjevrU6AsyxwmUx-nw1QZTfuYN28hXv23ViYj9o`; first-hand verification still owed). Do not build 6B.
- **7.** NIGGLES.md (Plan 00474): ACLs / `security.capability` not refused; step-2 resume test never seen failing on old code; other `worktree_blockers` callers keep a check-to-remove gap.
- **8.** PR #251 body: findings 1-4 fixed, open-descriptor row closed, open items above. Ends with the Claude Code generated line.
- Pre-push: `scripts/qa/error_hiding_exclusions.json` was NOT changed for the new `FileNotFoundError` catches (they use `log_and_continue`; the audit test passed). Invariant pairs, bandit and changed_tests_map not re-checked for step 5a.
