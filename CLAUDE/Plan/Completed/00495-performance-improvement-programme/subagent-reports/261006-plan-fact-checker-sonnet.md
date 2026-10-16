# Fact check: Plan 00495 PLAN.md

No REFUTED claims.

| #   | Claim                                                                                                        | Verdict           | Evidence                                                                                                |
| --- | ------------------------------------------------------------------------------------------------------------ | ----------------- | ------------------------------------------------------------------------------------------------------- |
| 1   | Plan 00154 (research) is complete                                                                            | VERIFIED          | Completed/00154-.../PLAN.md:3 `Status: Complete`                                                        |
| 2   | 00154 measured about 85 ms per tool call                                                                     | VERIFIED          | 00154 PLAN.md:125                                                                                       |
| 3   | 00154 measured a 1.26 s cold restart, import 141 ms                                                          | VERIFIED          | CLAUDE/Performance/BASELINE.md:36                                                                       |
| 4   | Full Rust rewrite ruled out: saves 4% end to end at most, costs auditability                                 | VERIFIED          | 00154 PLAN.md:127-128                                                                                   |
| 5   | The only Rust step judged worth having is a policy-free transport forwarder                                  | VERIFIED          | 00154 PLAN.md:128-129                                                                                   |
| 6   | That forwarder now exists as `relay/hooks_relay.rs` (Plan 00290)                                             | VERIFIED          | relay/hooks_relay.rs tracked; header line 3 cites Plan 00290; 00290 is Complete                         |
| 7   | Plans 00155 and 00156 are the tuning waves (cache per-Bash git fork, drop jq, slim init.sh), both complete   | VERIFIED          | 00155 PLAN.md:31 and :44; 00156 title and :18; both `Status: Complete`                                  |
| 8   | `CLAUDE/Performance/BASELINE.md` exists and marks the daemon dispatch figure "not re-measured"               | VERIFIED          | BASELINE.md:24                                                                                          |
| 9   | SessionStart handlers `git-upstream-checker`, `plan-qa-sweep`, `docs-qa-sweep`, `reference-repo-sweep` exist | VERIFIED          | handlers/session_start/{git_upstream_checker,plan_qa_sweep,docs_qa_sweep,reference_repo_sweep}.py       |
| 10  | A 20 s dispatch budget exists                                                                                | VERIFIED          | constants/timeout.py:77 `CHAIN_DEADLINE_DEFAULT = 20`                                                   |
| 11  | A 30 s socket timeout exists                                                                                 | VERIFIED          | constants/timeout.py:34 DAEMON_STARTUP=30, :48 REQUEST_DEFAULT=30                                       |
| 12  | The daemon denies hooks with "the daemon is starting"                                                        | VERIFIED          | constants/timeout.py:202 comment quotes the deny text, and `grep -rn "daemon is starting" src` finds it |
| 13  | `CLAUDE/Performance/README.md` exists and can record a budget                                                | VERIFIED          | The file exists, and its lines 5, 24 and 26 discuss budgets                                             |
| 14  | Status line is a separate component and has a handler                                                        | VERIFIED          | CLAUDE/Architecture/StatusLine.md is listed in CLAUDE/CLAUDE.md. I did not read the file.               |
| 15  | The SessionStart chain ran past 20 s and dropped 16 handlers in the 2026-10-06 session                       | UNVERIFIABLE-HERE | Session runtime evidence; settled only by that session's logs                                           |
| 16  | Hook calls were denied after a restart, and one hit the 30 s timeout                                         | UNVERIFIABLE-HERE | Runtime evidence; needs the daemon logs                                                                 |
| 17  | Another agent ran about 200 test files at the time                                                           | UNVERIFIABLE-HERE | Runtime evidence; needs the host process history                                                        |
| 18  | `untracked/scratch/startup-profile/REPORT.md` is the report path                                             | UNVERIFIABLE-HERE | A future artefact (Task 1.1 in progress), not a current-state claim                                     |

Note: Performance/README.md:72 lists the Rust forwarder as "Never, until free wins land + budget still fails", while `relay/hooks_relay.rs` exists. That does not contradict the plan. It is a stale backlog row the plan may want to correct.
