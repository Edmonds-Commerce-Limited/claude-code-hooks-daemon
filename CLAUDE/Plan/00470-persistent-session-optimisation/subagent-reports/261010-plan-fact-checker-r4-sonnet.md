# Fact check r4: Plan 00470 (Task 4.4 gap profile, RUNBOOK 3a)

Summary: 11 claims: 10 verified, 1 refuted (partly), 0 unverifiable.

## REFUTED

- **R1**: "the verdict log's rule field is empty (ledger N393)". The report itself says the field is null "for these handlers". Across `untracked/logs/hooks/verdicts.jsonl` 1,139 records carry a non-null rule (all `orchestrator-simulate`, rule = a command name such as `echo`), 22,846 are null. `usage-pause-gate` and `failsafe-cron*` records are null, so the practical conclusion holds. Change: say "empty for the cron and usage-pause handlers".

## Table

| #   | Claim                                                            | Verdict          | Evidence                                                                              |
| --- | ---------------------------------------------------------------- | ---------------- | ------------------------------------------------------------------------------------- |
| 1   | 4 main sessions, 2026-09-15 to 2026-10-10                        | VERIFIED         | report Scope: 5 transcripts, 120a0cfb excluded; span 09-15 to 10-10                   |
| 2   | 24,075 gaps; p50 6.5 s, p95 326 s, p99 1,764 s; 5.24% over 5 min | VERIFIED         | report "ALL gaps" row                                                                 |
| 3   | 17 over 60 minutes, nine of them usage-limit outages             | VERIFIED         | report: "Of the 17 gaps over 60 minutes, 9 are outages"                               |
| 4   | outside outages 0.03% and a maximum of 38,580 s                  | VERIFIED         | report "Excluding 429-outage gaps" row                                                |
| 5   | ticks, long tool calls, task notifications end most long gaps    | VERIFIED         | over-5-minute enders: 470 + 272 + 266 = 1,008 of 1,247 (81%)                          |
| 6   | not a human-paced profile; 00452 Task 2.4 still needs one        | VERIFIED         | report "Does NOT answer"                                                              |
| 7   | corrects 00452's "maximum 3,598 s, none over an hour"            | VERIFIED         | report "Relation to what 00452 already records"                                       |
| 8   | Dropped ticks could not be counted                               | VERIFIED         | report "Gaps coinciding with dropped ticks" 1                                         |
| 9   | verdict log rule field empty (N393)                              | REFUTED (partly) | see R1                                                                                |
| 10  | RUNBOOK.md has section 3a, link target exists                    | VERIFIED         | RUNBOOK.md heading "3a. Bound Claude Code's transcripts"                              |
| 11  | Task 4.1 measured 2.9 GB, 2.3 GB sub-agent                       | VERIFIED         | subagent-reports/261009-fact-check-task-4.1-sonnet.md rows 2 and 3 (2919 MB, 2378 MB) |
