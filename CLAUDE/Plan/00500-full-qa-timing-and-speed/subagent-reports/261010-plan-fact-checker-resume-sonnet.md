# Fact check: Plan 00500 resume Success Criterion (diff-added claims)

| #   | Claim                                                                                                    | Verdict                                    | Evidence                                                                                                                                                                                                                                                          |
| --- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "`all` interrupted (SIGINT) ... after 41 steps"                                                          | VERIFIED (41), partly unverifiable (where) | resume-check-2a.txt has 41 result lines (39 pass, 1 plan_qa fail, 1 project_handlers not-meaningful). Ends in KeyboardInterrupt in subprocess.run (llm_qa.py:1580). The trace does not name the tool being run, so "in the test matrix" is not shown by the file. |
| 2   | "`all --resume` on the unchanged tree printed 'reused, passed on this tree' for 40 steps"                | VERIFIED                                   | resume-check-2b.txt: 40 lines say "reused, passed on this tree" (39 with the recycle mark plus project_handlers with the circle mark).                                                                                                                            |
| 3   | "about 293 s of step time not repeated"                                                                  | VERIFIED                                   | Sum of "took N s" over the 40 reused lines is 292.6 s. Excluding project_handlers (12.7 s) it is 279.9 s over 39.                                                                                                                                                 |
| 4   | "re-ran the one that had failed, plan_qa"                                                                | VERIFIED                                   | 2a: plan_qa is the only failing step (1 advise finding). 2b: plan_qa is the only step with no "reused" marker and it reports the same finding again.                                                                                                              |
| 5   | "at af764fec1"                                                                                           | VERIFIED                                   | git log: af764fec1 (22:31:10) was HEAD when both files were written (22:53 and 22:56:18). HEAD 577257a2e (22:56:42) changed only PLAN.md and the JOURNAL.                                                                                                         |
| 6   | "after a mid-run commit changed the tree, `all --resume` re-ran every step and reused only `smoke_test`" | UNVERIFIABLE-HERE                          | The earlier run's output is not in the two files. The PLAN.md text it replaces made the same claim.                                                                                                                                                               |

## REFUTED claims

None.

## Caveats

- The resumed run in 2b also ends in KeyboardInterrupt, so it was cut short after plan_qa and project_handlers. The "40 reused" count is true, but 2b is not a complete gate.
- project_handlers is marked "NOT MEANINGFUL: detector failed: plan_qa" in both runs, yet 2b counts it as reused. It is included in the 40 and in the 293 s.
- "Unchanged tree" rests on the reuse behaviour itself and on HEAD being af764fec1. The files do not record a clean working tree.
