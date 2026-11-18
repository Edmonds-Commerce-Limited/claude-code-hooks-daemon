# Fact check: Plan 00622 Task 1.1 diff

Paths: R = src/claude_code_hooks_daemon/core/remote_branch_proof.py, B = src/claude_code_hooks_daemon/daemon/branch_safety.py

## REFUTED

1. "(c) ... git cherry also marks two CONTENT commits unmerged ... so only the net-change and file-survival proofs can pass it ... Test both the cherry and the net-change routes."
   - In the remote proof, cherry is not a proving route. R `_judge_offline` (R:374-394): `holds_net_change` "comes FIRST and alone decides"; `patch_equivalent` only names the tier afterwards. R header (R:17-19): "patch-id evidence never proves a branch alone". So shape (c) cannot be refused by cherry on the remote path, and there is no cherry route to test there.
   - File-survival (`content_unique_paths_of`) exists only in B (B:844), not in R. In B, `content-preserved` needs BOTH blob survival and net change (B:836-846), so "only net-change and file-survival" is wrong in the sense of "either"; both are required locally, and only net-change exists remotely.
   - A cherry route exists only in B (`patch_equivalent`, tier patch-equivalent, B:606-616, B:~800).
   - Plan change: say the remote proof is net-change only; the cherry route is a local-only (B) tier; the local content tier needs both blob survival and net change. Also note a "modified version merged" shape passes net change only if the default holds the same blobs and modes as the branch's net diff (R:339-345); a patch changed in the PR may fail it, so state the expected outcome of (c) rather than assume it passes.

## Table

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | The current proof refuses (a) empty unpark commit on top of merged content | UNVERIFIABLE-HERE | Not reproduced; the plan itself says so. Net change (R:362) ignores empty commits by construction, so the remote path may already pass it; needs the RED test. |
| 2 | (b) a park marker commit is refused by the current proof | Doubtful | R:18-21 and B:72 describe an existing `park-carried` exception (`branch_park.is_park_residue`), so some park shapes are already handled. Not run. |
| 3 | The peer measured (c) on one branch (cherry marks two content commits unmerged; default merged a modified version) | UNVERIFIABLE-HERE | External report; needs the peer's repo. |
| 4 | A net-change proof exists | VERIFIED | R:331 `holds_net_change`; B:644 `_net_change_held`. |
| 5 | A file-survival proof exists | VERIFIED (local only) | B:560 `content_unique_paths_of`, used at B:844. Absent from R. |
| 6 | A cherry route exists | VERIFIED (local only) | B:484 `cherry_unique_shas`, B:606 `patch_equivalent`. In R, cherry only picks the tier (R:390). |
| 7 | Only net-change and file-survival can pass (c) | REFUTED | See above. |
| 8 | Skipping empty commits alone is necessary but not sufficient | UNVERIFIABLE-HERE | A design assertion; follows from #3 if it holds. |
