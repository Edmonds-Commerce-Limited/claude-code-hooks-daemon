## 07:54 · decision · — — Stand-in ruling: parked-slot blocker

Stand-in ruling (automated one-off, NOT the owner). No owner message arrived since the awaiting-human stop.

Pending question: three follow-up fixes (`work-queue done` re-caching the finished issue as workable; acceptance `_discover_socket` missing the `/tmp` fallback socket; `branch_creation_guard` missing `git worktree add` inside `scripts/setup_worktree.sh`) each need a new branch, and `branch-preflight` reports creation blocked by R-BRANCH-PARKED-POOL: parked cap 1, slot held by `worktree-476-ci-gate-trial` (10d old). Options: (A) the owner deletes the remote branch; (B) the agent clears the park and merges the branch into main.

Ruling: DECLINED, stays blocked. Nothing merged, cleared or deleted.

Reasons:

- (A) is a remote branch delete, reserved for a human.
- (B) is not a sound engineering choice. Plan 00476's journal (2026-10-22, handoff 061736Z) records that the trial branch "is not to be merged" and that its reports are already kept on main in `b19221319`. The park commit `58e0511e4` repeats this and adds "Deletion of the unmerged branch is the owner's call."
- What the branch carries beyond main (`git diff --stat main...origin/worktree-476-ci-gate-trial`, 5 commits): `.github/workflows/full-gate-trial.yml` (171 lines), two trial reports, and a one-line PLAN.md change. A merge would put a trial CI workflow, which Plan 00476 finished without, onto main, purely to free a slot. A merge that discarded the content (an `ours` strategy) would be a deletion in disguise. Either way the merge would exist to get round the cap, not because the work belongs on main.
- The branch exists only as `origin/worktree-476-ci-gate-trial`; there is no local branch. Every way of freeing the slot other than merging ends in deleting that remote branch, including `bin/hooks-daemon delete-branch`.
- This is not the same question as Plan 00594's six declined rulings (recovery bundles, `--allow-unproven`, cap exits, `wip.creation_grace`), but it is of the same kind: the fate of a parked, unmerged branch, which the record already assigns to the owner.

What the owner can do to unblock, any one of: delete the remote branch (A); raise `branches.parked.cap`; or say that the trial workflow should be merged after all. The three fixes wait until then. A later real owner message can overturn this ruling.
