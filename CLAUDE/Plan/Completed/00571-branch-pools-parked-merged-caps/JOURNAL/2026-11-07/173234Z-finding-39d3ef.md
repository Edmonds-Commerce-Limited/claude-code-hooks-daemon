## 17:32 · finding · —   — branch hygiene dogfood observations

Branch-hygiene dogfood observations, coordinator session, 7 November 2026.

1. `delete-branch` run five times (one merged branch per call) left `untracked/deleted-branches.bundle` holding only the last branch (`git bundle list-heads`). Root cause in ROOTCAUSE.md item 1. Becomes Task 2.1.
2. `branch-sweep`'s "Merged, not deleted" list printed one `delete-branch` line per branch and never named `branch-sweep --clean`. That is how the five separate calls in (1) happened. Becomes Task 2.3.
3. `worktree-reap --reap --reap-branches` removed the worktree and its checked-out branch (`integration-174`) but silently left `worktree-issue-174-screen-arch`, merged and without a worktree. The skip is by design (non-agent name). The silence is the defect. Becomes Task 2.4.
4. After the reap, both #174 branches remained on origin; the sweep correctly gave remote-only advice. `--clean` has no remote path. Becomes Task 2.2.
5. Cap count: 9 of 10 this morning = 5 merged-undeleted + 3 live + 1 parked. After cleanup, 2 of 10. Merged and parked counting toward the cap is #165 plus the owner's ruling (three pools).
6. The branch stop guard asked the coordinator to push/finish `worktree-plan-00571-branch-pools` while this plan's sub-agent (work-queue `running`) was committing to it, threatening "abandoned" at block 3. N581 reproduced. Tip pushed as a backup (548196299). Becomes Task 2.5, sent to the sub-agent.
7. A PreToolUse chain judgement exceeded its 19.95 s dispatch budget once, while three QA runs loaded the host, and failed closed; the retry passed. Noted, not acted on.
8. The open niggles ledger (Plan 00474) refused an edit: its `**GitHub Issue**: #59` header is assigned to another account, so R-GH-ISSUE-ASSIGNED-ELSEWHERE denies every write to it. Raised with the owner.
