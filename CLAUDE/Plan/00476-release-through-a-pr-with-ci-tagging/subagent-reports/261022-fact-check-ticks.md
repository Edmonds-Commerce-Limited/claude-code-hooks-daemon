# Fact check: Plan 00476 PLAN.md diff (status flip, ticks, Delivery)

## REFUTED (most consequential first)

1. "8 test shards (`scripts/qa/test_shards.yaml`)" (Task 1.2). The file defines 7 shards:
   `grep -c "^  - name:"` gives 7 (unit-handlers, unit-daemon, unit-core, unit-features,
   unit-tooling, integration, acceptance-and-other). Change "8" to "7". The findings report
   (261022-task-1.1-1.2-findings-sonnet.md) does not say 8 either: it proposes four check
   groups plus six test runners (3 Pythons x unit/rest), so "4 check groups and 8 test
   shards" mixes sources.

## Qualified (not refuted)

- "`tests` needed a daemon keepalive" (Task 1.1): the findings report (lines 20-37) says the cause
  is "established from the code, not yet confirmed by a run"; the keepalive was added to the trial
  workflow and the re-run result is not recorded. The 11th error (test_forwarder_socket_stdin) is
  "PROBABLY" the same cause, not proven. The plan states this as settled.

## Table

| #   | Claim                                                    | Verdict   | Evidence                                                                                                                         |
| --- | -------------------------------------------------------- | --------- | -------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Commit `c7637cf1c` is on main (Task 2.1)                 | VERIFIED  | `git merge-base --is-ancestor c7637cf1c main` true; subject "Merge worktree-476-release-pr-workflow ... Task 2.1"                |
| 2   | Commit `1ad2e3618` is on main (Task 3.1)                 | VERIFIED  | ancestor of main; subject "Merge worktree-476-release-procedure ... Task 3.1"                                                    |
| 3   | Run 39728713370 green on main                            | VERIFIED  | `gh run view 39728713370 --json conclusion,headBranch,headSha,workflowName` gives success, main, 1ad2e36188b9..., "Release gate" |
| 4   | 43 `llm_qa.py` checks                                    | VERIFIED  | `len(llm_qa.ALL_TOOL_NAMES)` is 43; trial report line 11 says the same                                                           |
| 5   | 8 shards in `scripts/qa/test_shards.yaml`                | REFUTED   | 7 shards, see above                                                                                                              |
| 6   | Report `261022-task-1.1-trial-workflow-sonnet.md` exists | VERIFIED  | listed in subagent-reports/                                                                                                      |
| 7   | Report `261022-task-1.1-1.2-findings-sonnet.md` exists   | VERIFIED  | listed in subagent-reports/                                                                                                      |
| 8   | "42 of 43 ran unchanged"                                 | VERIFIED  | findings report line 8: "42 of 43 passed unchanged"                                                                              |
| 9   | "`tests` needed a daemon keepalive"                      | Qualified | cause unconfirmed by a run, see above                                                                                            |
| 10  | `scripts/release/check_release_ci.py` exists             | VERIFIED  | file present                                                                                                                     |
| 11  | `perf_sweep` marker exists                               | VERIFIED  | pyproject.toml line 131                                                                                                          |

Not checked: the 7 tests / 11 cases count for `scaled_cpu_seconds`, the `release_merge_freeze`
handler details, and the RELEASING.md step list.
