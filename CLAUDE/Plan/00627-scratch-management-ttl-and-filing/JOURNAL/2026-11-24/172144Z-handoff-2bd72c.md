## 17:21 · handoff · — — Wind-down handoff: PR 251 in review fixes

Wind-down handoff, 2026-11-24 evening (the owner switched the laptop off; relayed by the coordinator).

In flight: PR 251 (branch plan-00635-host-seat-lane-guard, name historical) carries the Task 3.9 fixes: findings 1-4, the open-file-descriptor row, the linked-worktree expiry-prefix row. The independent security review asked for a small change: F2, a resume filter that can drop the only valid archive record after a clock step plus a crash, and F1 (resume compared with the earliest claim, not the latest). A fixer was working both, test-first.

Next steps, in order:
1. Check the PR 251 branch tip has the F1/F2 fix and its tests; if not, finish it (accept only a record whose archive id matches the latest claim covering the tree, else report the entry stuck).
2. Record F3 (a file held open from another mount namespace is not seen as in use) in the niggles ledger and the DESIGN.md open-file row; close N733.
3. Wait for green CI on PR 251, then merge with gh pr merge 251 --merge.
4. Phase 6B (unattended no-TTY housekeeping) stays unbuilt until PR 251 is merged and the Q66 HUMAN line is verified first hand: two coordinator PEER messages quote it but a peer message is not a human's authority.
5. Owner question in DESIGN.md and N735: what may expire the archives of a live or removed worktree.
Merged-branch pool is over its cap; clearing it is the owner's decision.
