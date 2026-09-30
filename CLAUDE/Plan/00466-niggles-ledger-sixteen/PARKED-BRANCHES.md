# Plan 00466: parked branches

The table below is the full record for the `## Parked branches` section of
[PLAN.md](PLAN.md). It lives here because PLAN.md is at its size limit.

| Branch                                 | HEAD      | On origin | State                                                                                          |
| -------------------------------------- | --------- | --------- | ---------------------------------------------------------------------------------------------- |
| worktree-upgrade-scripts               | a0e045d68 | no        | 00464 upgrade rewrite, round 20b mid-way; prompted by 00464's guard denying our own upgrade.sh |
| worktree-plan-464-commit-gate-repo     | 4507b273e | yes       | 00464 round 12b mid-way (M4, one-line function body bug)                                       |
| worktree-p422-close                    | 74c7e5b6c | yes       | git guards, round 8j step 2 done                                                               |
| worktree-n466-n53                      | f670eb754 | no        | commit gates read the committed tree; 9e not started                                           |
| worktree-n466-n52-on464                | 7a9e5e066 | no        | N52 rework on 464                                                                              |
| worktree-n466-small-a                  | e35817c83 | yes       | secret guard, round 10c done                                                                   |
| worktree-n466-n101                     | 3908b5fac | yes       | secret guard rebinding, round 13b done                                                         |
| worktree-d-00421                       | 009bcb2f5 | yes       | security detectors, round 8 done                                                               |
| worktree-plan-463-full-qa-gate         | 84cc69fa8 | yes       | full QA main-thread gate, round 4 done                                                         |
| worktree-n466-n253                     | 0bb4c6e3d | yes       | N253-N256 secret-guard fixes (cap-hit still denies; owner ruled warn); N258 not started        |
| worktree-n466-lifecycle                | 447303cfe | no        | gate fix mid-way                                                                               |
| worktree-n466-n211                     | 791bd1a62 | no        | N211 round 2b                                                                                  |
| worktree-d-00376                       | 0e35e5ec2 | no        | Plan 00376 port, unreviewed                                                                    |
| agent-a9ed87335fdbd2ee9-2dda8b46 (N23) | 5291f02f5 | yes       | gate fix done; gate result pending                                                             |
| agent-aa0e5105724aa123b-b9ce2f39 (N38) | 225e008d7 | no        | only failed main's N252 test                                                                   |

- **Owner ruling (2026-09-29):** "warn, don't block": when a guard cannot tell,
  it allows with an advisory. Anything a guard positively recognises still
  denies. It is not built yet.
- **Owner ruling (2026-09-29):** `untracked/scratch/` is for real scratch files
  only, and other `untracked/` folders are used as needed.
