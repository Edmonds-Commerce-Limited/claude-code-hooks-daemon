# Plan fact check, Plan 00618 (diff-scoped)

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Red/fix commits cd6631424, 8d0e37de4, 09f149d7c, 6e16b8ac8, 9111cee6c, 95e5dc55e, d4aa70de7, 9348caa50, 2f3349403, d4974189c, 42180df61, 7f0331142 are on main | VERIFIED | git cat-file / merge-base --is-ancestor main: all exist, all ancestors |
| 2 | 873880239 (format fix of Plan 00609 script) on main | VERIFIED | ancestor of main; subject "black-format an archived Plan 00609 probe script" |
| 3 | Merge 73cd364e5 is Phase 2 merge, on main | VERIFIED | ancestor; subject matches |
| 4 | CI run 44000713338 green on the Phase 2 merge | VERIFIED (imprecise) | gh: conclusion success, workflow QA, headSha e53eef183 (the merged branch tip, ancestor of 73cd364e5), not the merge commit itself |
| 5 | Run 43961579876 was the red gate on the aborted release head | PARTLY | gh: conclusion failure, headSha 70c48bf55; failure cause (format check) not checked here |
| 6 | Release notes 089 to 092 exist | VERIFIED | CLAUDE/UPGRADES/UNRELEASED/release-notes/089..092-*.md present |
| 7 | Cited subagent-reports exist (261116-fix-b1-b2, fix-b2-rework, fix-b3-b5, 261117-fix-older-holes-review, 261117-phase2-defects) | VERIFIED | ls of subagent-reports/ |
| 8 | "17 fixed + N-16 already fixed", "29 of 33", "12 of 13 nits" counts | UNVERIFIABLE-HERE | arithmetic not checkable without the review report; not reconciled |
| 9 | D-1..D-4 behaviour claims (stop guard tests mode != off; N-8 name count; bash -s; PostToolUse 15 s/20 s budgets) | UNVERIFIABLE-HERE | not searched in daemon source; needs code read |
| 10 | Harness half of Task 2.5 on main; gate not run on merged tip | UNVERIFIABLE-HERE | no commit cited |

REFUTED: none.
