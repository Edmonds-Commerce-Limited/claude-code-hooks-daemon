# Fact check: Plan 00627 Task 6B.1 (merged-branch pool case, N714)

Diff: /workspace/untracked/plan-fact-check/00627-scratch-management-ttl-and-filing.diff. Judged against the current tree on main (c80c096d5).

Added text: "This path must also clear the merged-branch pool case (Plan 00474 N714): a merged branch whose worktree holds only proof-cleared scratch is reaped and its branch deleted, so the pool cap never needs a human terminal; a test pins that the pool count drops after such a reap."

## REFUTED

None.

## Claims

| #   | Claim                                                                                 | Verdict                 | Evidence                                                                                                                                                                                                                                                                 |
| --- | ------------------------------------------------------------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Plan 00474 N714 is the merged-branch pool case                                        | VERIFIED                | `00474/NIGGLES.md:8361` `### N714 the branch-pool warning keeps naming a branch that branch-keep already marked kept`, and its addendum links Plan 00627 Task 6B.1 (N714 is about the merged pool; `branch_ladder._command` returns the sweep command for `Pool.MERGED`) |
| 2   | A merged branch has a pool whose cap a human terminal currently has to clear          | VERIFIED (code reading) | `core/branch_creation.py` ~1049-1052 counts merged work against `effective_pool_cap(Pool.MERGED)`; the live warning shows the merged pool at 9 of 10; the N714 addendum names `worktree-reap --reap` (terminal) as the only route for scratch-holding worktrees          |
| 3   | `worktree-reap --reap` exists and is the existing reaper this path extends            | VERIFIED                | `daemon/worktree_evacuate.py:94`, `daemon/housekeeping.py:170`, `core/agent_ownership.py:107` build `worktree-reap --reap --only <name>`                                                                                                                                 |
| 4   | "the pool count drops after such a reap" is a testable property of the current design | VERIFIED (code reading) | `branch_creation.py` ~1049 builds the merged list from branch groups, so deleting the branch removes it from the count. Note the N714 addendum also says a KEPT branch stays counted, so the test must reap and delete, not keep. Not run.                               |
| 5   | Task 6B.1 sits under Phase 6B, owner ruling Q66, no-TTY proof-gated reap              | VERIFIED                | `00627/PLAN.md` lines 121-128                                                                                                                                                                                                                                            |
| 6   | The branch deletion is within the "proof-cleared" scope of the ruling                 | UNVERIFIABLE-HERE       | The relayed Q66 ruling (PLAN line 125) covers scratch and merged worktrees; branch deletion is an extension, and the Q66 HUMAN line is unverified (Task 6B.0 gate). Settled by the owner. Not a factual claim about code.                                                |

Totals: 6 claims: 5 verified, 0 refuted, 1 unverifiable.
