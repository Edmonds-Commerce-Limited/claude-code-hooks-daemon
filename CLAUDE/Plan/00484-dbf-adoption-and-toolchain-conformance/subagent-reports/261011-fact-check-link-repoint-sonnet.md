# Fact check: link repoint to archived plan 00483 (diff-scoped)

Claims checked: the 8 repointed references in PLAN.md (2), REVIEW-fable.md (5) and SUPPRESSIONS.md (1). Each now reads `../Completed/00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md`.

## REFUTED

None.

## Table

| #   | Claim                                                                                   | Verdict  | Evidence                                                                                                                                |
| --- | --------------------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | PLAN.md Task 1.4 link (C2) resolves to `../Completed/00483-.../OWNER-RULINGS-261005.md` | VERIFIED | File exists at CLAUDE/Plan/Completed/00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md; `## C2: 00484 Task 1.4` at line 140  |
| 2   | PLAN.md Phase 2 link (all five resolved)                                                | VERIFIED | Same target exists                                                                                                                      |
| 3   | REVIEW-fable.md DEFSET (C1)                                                             | VERIFIED | Target exists; `## C1: 00484 DEFSET` line 133                                                                                           |
| 4   | REVIEW-fable.md G1 (B2)                                                                 | VERIFIED | `## B2: 00484 G1, inline QA suppressions` line 97                                                                                       |
| 5   | REVIEW-fable.md G2 (B1)                                                                 | VERIFIED | `## B1` line 88                                                                                                                         |
| 6   | REVIEW-fable.md G4 (B3)                                                                 | VERIFIED | `## B3: 00484 G4` line 105                                                                                                              |
| 7   | SUPPRESSIONS.md ruling B2 path                                                          | VERIFIED | Same target; B2 at line 97                                                                                                              |
| 8   | The old path `../00483-...` is gone, and no stale refs remain in the 00484 .md files    | VERIFIED | `ls -d CLAUDE/Plan/00483*` returns no match. A grep for `00483-threat` in 00484 .md files excluding `Completed/00483` returned nothing. |

The plan files PLAN.md, REVIEW-fable.md and SUPPRESSIONS.md sit in CLAUDE/Plan/00484-.../, so `../Completed/` resolves to CLAUDE/Plan/Completed/.
