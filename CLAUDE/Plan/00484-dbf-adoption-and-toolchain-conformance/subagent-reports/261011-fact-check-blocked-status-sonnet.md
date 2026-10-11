# Fact check: Plan 00484 diff (Blocked status, Completed/ link paths)

REFUTED: none.

| #   | Claim                                                                                                                          | Verdict  | Evidence                                                                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------ | -------- | --------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Status is Blocked                                                                                                              | VERIFIED | PLAN.md:3 `**Status**: Blocked`; README.md:25 row says "Blocked on the owner"                                                     |
| 2   | OWNER-RULINGS-261005.md lives at `../Completed/00483-threat-model-conformance-audit/` relative to the plan folder (PLAN.md x2) | VERIFIED | `CLAUDE/Plan/Completed/00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md` exists                                       |
| 3   | Same path in REVIEW-fable.md (4 links)                                                                                         | VERIFIED | same file exists                                                                                                                  |
| 4   | Same path in SUPPRESSIONS.md (1 link)                                                                                          | VERIFIED | same file exists                                                                                                                  |
| 5   | The old path `../00483-...` is stale (implied)                                                                                 | VERIFIED | `ls -d CLAUDE/Plan/00483*` finds nothing; grep finds no remaining non-Completed 00483 link in the plan's .md files                |
| 6   | The owner questions sheet linked from the README row exists (referenced in the index)                                          | VERIFIED | README.md:25 links `00474-niggles-ledger-seventeen/OWNER-QUESTIONS-261011.md` (read from the grep; the file is outside this diff) |
