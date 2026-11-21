STOPPING BECAUSE: review complete. Verdict: **ISSUES, 1 Low, 0 Medium/High.**

The brief names no check id, so I applied F-BYPS to this one guard over `main...HEAD`. No other check was run.

**Low.** At `core/remote_branch_proof.py:252`, `_net_change` runs `git diff --raw` without `--ignore-submodules=none`. If the tracked `.gitmodules` has `submodule.X.ignore=all`, or `diff.ignoreSubmodules=all` is set, git drops the gitlink row. I confirmed this on git 2.47 in `untracked/scratch/secrev-sub`. A branch that bumps a submodule and adds one file a holder already has is then proven `surviving-content`, and the pointer change is lost. I inferred that end to end and did not run it through `prove_remote_merged`. It predates this branch: the shipped content-preserved tier calls `_net_change` too. Fix: pass `--ignore-submodules=none`, which I checked restores the row under both settings.

**Verified clean:**
- Every delete is fed only by `prove_remote_merged`, and the tier is never cached.
- Every holder and the remote default are anchored and confirmed live (`c20fd1570`).
- Empty, garbled or failed `ls-remote` output fails closed.
- Each push URL is checked, or the delete is refused (`79b8fa956`, `e8320a726`).
- `--remote-only` deletes with a per-ref `--force-with-lease`, and a test covers a tip that moves.

**Dismissed (threat model):** a remote named with a leading `-`. It needs `refs/remotes/<name>` to exist, and the proof refuses before any `ls-remote`.

The 8 test files: 150 passed. **Not checked:** git 2.56 (not available here). Already accepted, not re-raised: the raw unleased delete (Finding 4) and N680.

**Read in full:** `CHECKS.md`, the task 3.8 report, release note 010, the source diff. **Read in part:** `remote_branch_proof.py`, `branch_cleanup.py`, `destructive_git.py`, `git_repo.py`, `remote_refs.py`. **Not read:** PLAN/DESIGN, the earlier F-BYPS report (searched only), `Security/README.md`.