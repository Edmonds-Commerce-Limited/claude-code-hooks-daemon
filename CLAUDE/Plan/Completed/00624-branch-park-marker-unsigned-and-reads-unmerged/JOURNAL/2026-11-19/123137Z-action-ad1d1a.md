## 12:31 · action · —

Phase 1 done: reproduced #210 and #211 on main in scratch repos. #210 is already fixed by d2e73d0e9 (in v3.75.0, not v3.74.0); #211 is already fixed on the inventory, delete-branch and remote-delete paths by the park-carried and empty-commits-only tiers, and the guard still refuses real unmerged work. Findings: subagent-reports/repro-findings.md. Remaining: design 1 (park without a branch commit via refs/parked/<name>); the worktree reaper is left conservative.
