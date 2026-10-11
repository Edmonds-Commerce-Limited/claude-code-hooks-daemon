# Fact check: Plan 00470 blocked-status diff

Diff: /workspace/untracked/plan-fact-check/00470-persistent-session-optimisation.diff

## Results

No claim was refuted.

| #   | Claim                                                                                                                         | Verdict  | Evidence                                                                                                                                            |
| --- | ----------------------------------------------------------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "[RUNBOOK.md §3a](RUNBOOK.md)" exists                                                                                         | VERIFIED | RUNBOOK.md:63 `## 3a. Bound Claude Code's transcripts`                                                                                              |
| 2   | "Task 4.1 measured 2.9 GB, 2.3 GB of it sub-agent transcripts"                                                                | VERIFIED | PLAN.md:121 (2.9 GB, sub-agent 2.3 GB)                                                                                                              |
| 3   | Report `subagent-reports/261010-task-4.4-gap-profile-sonnet.md` exists                                                        | VERIFIED | `ls` lists it                                                                                                                                       |
| 4   | "4 main sessions, 2026-09-15 to 2026-10-10"                                                                                   | VERIFIED | Report lines 5-12: 5 transcripts, 120a0cfb excluded, so 4 included. Span 09-15 to 10-10                                                             |
| 5   | 24,075 gaps                                                                                                                   | VERIFIED | Report line 12 and table row                                                                                                                        |
| 6   | p50 6.5 s, p95 326 s, p99 1,764 s                                                                                             | VERIFIED | Report line 18 (6.5 / 326.4 / 1764.2)                                                                                                               |
| 7   | 5.24% over 5 minutes                                                                                                          | VERIFIED | Report line 18 (1,261, 5.24%)                                                                                                                       |
| 8   | 17 over 60 minutes, nine of them usage-limit outages                                                                          | VERIFIED | Report line 18 (17); 17 minus 8 non-outage gives 9 (line 19)                                                                                        |
| 9   | Outside outages 0.03%, max 38,580 s                                                                                           | VERIFIED | Report line 19                                                                                                                                      |
| 10  | Ticks, long tool calls and task notifications end most long gaps; not a human-paced profile                                   | VERIFIED | Over-5m non-outage gaps: 272 tool + 470 tick + 266 task-notification = 1,008 of 1,247. "Not a human-paced project" at report line 52                |
| 11  | 00452 Task 2.4 still needs a human-paced profile                                                                              | VERIFIED | 00452 PLAN.md:134 (Task 2.4 open, unchecked)                                                                                                        |
| 12  | Corrects 00452's "maximum 3,598 s, none over an hour"                                                                         | VERIFIED | 00452 PLAN.md:136-137 ("ZERO crossing the 1h TTL, largest gap 3,598s")                                                                              |
| 13  | Dropped ticks could not be counted: the verdict log's rule field is empty for the cron and usage-pause handlers (ledger N393) | VERIFIED | NIGGLES.md N393. The correction there says the field is null for `usage-pause-gate` and `failsafe-cron*`, which matches the plan's narrowed wording |
| 14  | 00452 Tasks 4.1-4.3 hold the warming design and arithmetic                                                                    | VERIFIED | 00452 PLAN.md:171, 175, 181                                                                                                                         |
| 15  | 00452 rejected a fixed-interval warming cron                                                                                  | VERIFIED | 00452 PLAN.md:61 (Non-Goals)                                                                                                                        |

Minor note: N393's original wording ("empty on every record") was later corrected in the ledger. The plan's wording already reflects the corrected scope.

## REFUTED

None.
