# Fact check r4: Plan 00474 NIGGLES.md (N393, N394)

Summary: 9 claims: 7 verified, 2 refuted, 0 unverifiable.

## REFUTED

- **R1 (N394)**: "`get_description()` in `handlers/user_prompt_submit/idle_housekeeping_advisor.py` says ...". That file defines no `get_description` (grep for `def get_description` finds none anywhere in `src`). The quoted text is in `get_claude_md()`. Fix the function name; the remedy "regenerate any generated docs that quote it" should name `get_claude_md`.
- **R2 (N393)**: "has an empty rule field on every record". `untracked/logs/hooks/verdicts.jsonl` has 1,139 non-null `rule` records (all handler `orchestrator-simulate`, rule = a command name such as `echo`, `bash`) against 22,846 null. For `usage-pause-gate` and `failsafe-cron*` the field is null, so the narrower statement holds. Also the log has grown past 16:04 (last record 2026-10-10 20:10), so the stated coverage end is stale.

## Table

| #   | Claim                                                                                | Verdict  | Evidence                                                                                                    |
| --- | ------------------------------------------------------------------------------------ | -------- | ----------------------------------------------------------------------------------------------------------- |
| 1   | N394: the wording says gone-branch refs come "with the `git update-ref -d` for each" | VERIFIED | `get_claude_md` text: "with the `git update-ref -d` for each"                                               |
| 2   | N394: it is in `get_description()`                                                   | REFUTED  | see R1                                                                                                      |
| 3   | N394: code prints at most 5 refs                                                     | VERIFIED | `utils/stale_litter.py` `MAX_LISTED_REFS = 5`, `gone[:MAX_LISTED_REFS]` (the command still names every ref) |
| 4   | N394: one `git update-ref --stdin` command for all                                   | VERIFIED | `stale_litter.py` report builder: `printf 'delete %s\n' ... \| git update-ref --stdin`                      |
| 5   | N393: log covers 2026-10-09 07:54 onwards                                            | VERIFIED | first record ts 2026-10-09T07:54:03                                                                         |
| 6   | N393: empty rule field on every record                                               | REFUTED  | see R2                                                                                                      |
| 7   | N393: only handler name `usage-pause-gate`, 28 denies usable                         | VERIFIED | `grep usage-pause-gate \| grep -c deny` = 28                                                                |
| 8   | N393: the three rule IDs cannot be counted from it                                   | VERIFIED | grep for R-FAILSAFE, R-USAGE-PAUSE, R-DECLARED in the log: 0                                                |
| 9   | N393: Plan 00484 3.1a made every deny path declare a rule                            | VERIFIED | 00484 PLAN.md 3.1a: "all nine identifier-less deny paths declare a rule"                                    |
