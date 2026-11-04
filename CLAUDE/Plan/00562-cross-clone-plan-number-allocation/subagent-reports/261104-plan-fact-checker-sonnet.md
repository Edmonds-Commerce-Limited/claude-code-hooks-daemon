# Plan 00562 fact check

The diff only deletes one Non-Goals clause ("The commit-time plan QA gate already reports duplicate numbers"). It adds no claim. The key claims were checked against the whole PLAN.md as the caller asked.

## REFUTED

1. R1: "plan_numbering.py (built by Plan 00144)" is wrong. `git log --follow` on `src/claude_code_hooks_daemon/handlers/utils/plan_numbering.py` shows the git-anchored counter helpers arrived in commit 988943bb9, "Plan 00112 Phase 2". The file first appears in 41af5d1d2 (2026-01-28). Plan 00144 only reuses it: PLAN.md line 79 of that plan lists it as an existing utility. Fix: name Plan 00112 (Completed/00112-git-anchored-plan-numbering).

## Table

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | plan_numbering.py takes the higher of the git counter and the on-disk highest | VERIFIED | plan_numbering.py:184 `max(counter, highest_plan_number(...))` |
| 2 | mkplan.bash takes the higher of the two | VERIFIED | mkplan.bash:807-820 `fs_highest` replaces the counter when it is higher, and the header comment at line 50 says the same |
| 3 | Plan 00144 built plan_numbering.py | REFUTED | see R1 |
| 4 | Plan 00474 / #59 added the scaffold lock | VERIFIED, with a caveat | 00474 PLAN.md line 9 names #59, "the mkplan.bash worktree lock", released in v3.68.0. The lock sits in the repository's COMMON git dir (mkplan.bash:39), so it is per-repository and covers linked worktrees. It is not strictly per-checkout |
| 5 | Timeout.GIT_FETCH_SESSION exists | VERIFIED | constants/timeout.py:171 `GIT_FETCH_SESSION = 30` |
| 6 | Plan 00558 deferred cross-clone collisions | VERIFIED | 00558 PLAN.md line 53: "Plan-number collisions across clones (raised on #152; filed separately as Plan 00562, GitHub #154)" |
| 7 | The counter is per-clone (`git config --local`) | VERIFIED | plan_numbering.py:11 |
| 8 | Both sources are local, so another clone's plan is invisible | VERIFIED | Follows from #1 and #2. Neither does any fetch or remote read |
| 9 | CLAUDE/UPGRADES/UNRELEASED/ is the holding area | VERIFIED | The directory exists and holds release-notes/ |
| 10 | The observed field case was reported on #152 | UNVERIFIABLE-HERE | GitHub issue content was not checked |
