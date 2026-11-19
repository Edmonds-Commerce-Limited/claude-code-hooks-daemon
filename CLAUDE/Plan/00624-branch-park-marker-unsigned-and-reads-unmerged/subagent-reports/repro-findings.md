# Plan 00624 Phase 1: what main already fixes

Reproduced on main at `3d9d89547` (v3.75.0 plus later merges), worktree `src`, scratch
repos with a bare local remote. Script: `untracked/scratch/00624/repro.py` (untracked);
it calls the library entry points the CLI and handlers use: `park_branch`,
`build_inventory` (pools, sweep), `classify_branch` (`delete-branch`, local
`branch-sweep --clean`), `prove_remote_merged` (the `R-GIT-PUSH-DELETE-REMOTE` guard and
`branch-sweep --clean --remote`), `cherry_unique_shas`.

## Issue #210 (unsigned marker): already fixed

`d2e73d0e9` (Plan 00594 Task 4.9) signs the park and unpark commit with
`commit-tree -S` when `commit.gpgsign` is true; it is in v3.75.0, not v3.74.0 (the
reported version). Verified with an ssh signing key: real commit, park marker and
unpark marker all carry `gpgsig`. `branch-park` runs in the CLI process (`cmd_branch_park`
calls `park_branch` directly), so `commit-tree -S` inherits the caller's environment,
including `SSH_AUTH_SOCK` for an agent-held key. Existing tests:
`tests/unit/core/test_branch_park_signing.py`, `tests/integration/test_branch_park_signed_commits_e2e.py`.

## Issue #211 (markers read unmerged): already fixed on every named path

| Scenario                                           | inventory        | classify (delete-branch) | remote-delete proof |
| -------------------------------------------------- | ---------------- | ------------------------ | ------------------- |
| park, real commit ff-landed                        | park-carried     | park-carried             | park-carried        |
| park + unpark, ff-landed                           | park-carried     | park-carried             | park-carried        |
| park, landed by `--no-ff` merge                    | park-carried     | park-carried             | park-carried        |
| park, landed by cherry-pick                        | park-carried     | park-carried             | park-carried        |
| park, landed by squash                             | patch-equivalent | patch-equivalent         | patch-equivalent    |
| REFUSE: park, then real unmerged commit            | live             | unproven                 | refused             |
| REFUSE: file-changing commit with the park message | parked           | unproven                 | refused             |

`park-carried` (Plan 00594/00617) and `empty-commits-only` (Plan 00622) do the work.
The guard still bites on real work. Raw `git merge-base --is-ancestor` (the issue's
step 5) and raw `git cherry` still see the markers: that is git, not the daemon.

## Still open

- **Markers are still written onto the branch.** Owner's design 1 (park without a
  branch commit) is not done: Phase 2.
- **Worktree reaper** (`core/worktree_reaping.py`) counts markers through
  `rev-list --count base..HEAD` and `git cherry`, so a merged-but-parked worktree is
  kept for a human. That predicate is deliberately conservative (module docstring);
  left as-is and reported.
- A file-changing commit that carries the park message reads `parked` (dormancy
  exemption) in the inventory. Never a merged proof, so no deletion risk; noted.
