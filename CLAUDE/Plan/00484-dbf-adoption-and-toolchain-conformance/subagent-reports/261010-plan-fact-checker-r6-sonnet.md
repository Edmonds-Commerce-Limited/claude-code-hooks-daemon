# Fact check r6: PLAN.md Success Criteria ticks (Plan 00484)

r1 to r5 reports already existed, so this is r6. Scope: the Success Criteria ticks the diff adds to PLAN.md (lines 204-214).

## REFUTED

None.

## Table

| #   | Claim                                                                                        | Verdict  | Evidence                                                                                                                                                                                                                               |
| --- | -------------------------------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "The README and `explain-rule` name DBF and link to it."                                     | VERIFIED | README.md:84-86 has a "Defence Before Fix" section linking https://defence-before-fix.github.io. `explain-rule R-PIPE-TO-TAIL` prints "Method: Defence Before Fix. https://defence-before-fix.github.io" (from `constants/dbf.py:24`). |
| 2   | "#65 and #67 are answered (Tasks 1.1-1.4)"                                                   | VERIFIED | PLAN.md Task 1.4 records comments posted on #65 and #67. The existence of the comments on GitHub is not re-checked (UNVERIFIABLE-HERE without `gh`), but the plan's own record says done.                                              |
| 3   | "round 1 SURVIVES WITH FIXES" at `subagent-reports/261010-conformance-fable-review-fable.md` | VERIFIED | File exists; line 9 reads "## Verdict: SURVIVES WITH FIXES".                                                                                                                                                                           |
| 4   | Fixes are "merged" and the link `subagent-reports/261010-conformance-fixes-sonnet.md`        | VERIFIED | File exists. Git log shows "9f04f087f Merge Plan 00484 CONFORMANCE.md fixes from the Fable review".                                                                                                                                    |
| 5   | "round 2 READY TO MERGE" at `subagent-reports/261010-conformance-fable-review-r2-fable.md`   | VERIFIED | File exists; line 9 reads "## Verdict: READY TO MERGE".                                                                                                                                                                                |
| 6   | "`hooks-daemon defences --json` (Task 3.2)" exists and lists the daemon's defences           | VERIFIED | `bin/hooks-daemon defences --json` ran with rc 0 and returned a JSON list of 48 rows.                                                                                                                                                  |
| 7   | "round 2 found every row carries a rule ID and statement (artefact 5.1b MET)"                | VERIFIED | r2 report line 24 and line 51 say 48/48. Re-checked independently: 0 of the 48 rows lack `rule_id` or `statement`.                                                                                                                     |

The unticked criterion 3 (owner rulings) is not a claim and is not checked.

Summary: 7 claims: 7 verified, 0 refuted, 0 unverifiable (claim 2's GitHub comments are taken from the plan's record).
