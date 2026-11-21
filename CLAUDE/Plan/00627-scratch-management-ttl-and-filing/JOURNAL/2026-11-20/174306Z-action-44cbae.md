## 17:43 · action · Task 3.0 — Task 3.0 closed in DESIGN section 13 and PLAN.md

Task 3.0 complete. DESIGN.md section 13: the N1, N2, N3, N4 and reflog/`ORIG_HEAD` rows are marked closed, each naming the module and the mechanism; the F-BYPS F1/F2 rows no longer point at open rows. PLAN.md: Task 3.0 ticked, and Task 3.9 now reviews the Task 3.0 fixes instead of ruling on an open row.

Residuals for Task 3.9: a clone with more than MAX_TIPS distinct reflog commits is PROTECTED even when all are pushed (fail closed); a value-less `core.bare` (which git reads as true) is treated as not bare (fail closed, PROTECTED).
