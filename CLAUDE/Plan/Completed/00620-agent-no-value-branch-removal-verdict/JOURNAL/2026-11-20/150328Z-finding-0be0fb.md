## 15:03 · finding · —

D-EXEC re-check hypothesis CONFIRMED and fixed: `_compare_and_delete` trusted only the `branch ` lines of `git worktree list --porcelain`, so a branch mid-rebase (merge or apply backend, or named in `rebase-merge/update-refs`) or mid-bisect in any worktree — HEAD detached there — was deleted by `update-ref --no-deref -d`, which `git branch -D` would have refused. Red tests deleted the branch in all 7 new cases.

Measured on git 2.47.3 (scratch probe): after the delete, `rebase --continue` fails with "could not update refs/heads/feat" and the rebased commits stay on a detached HEAD only. DESIGN.md's residue paragraph claimed the rebase recreates the branch; that was wrong and is rewritten.

Fix: one helper `_operation_holding_branch` reads every admin dir (common dir + `worktrees/*`) for `rebase-merge|rebase-apply/head-name`, `rebase-merge/update-refs` (every third line) and `BISECT_START`, exact match; absent file = no operation, any other OSError or a failed `--git-common-dir` refuses. Stopped merge/cherry-pick/revert keep HEAD attached, so the existing check refuses them; pinned as regression tests, no new reads.

Scope: delete path only. `classify_branch`/`worktree_branches` unchanged, so a dry run can still report such a branch eligible, and a refusal at delete time consumes the verdicts (fail closed, as for every git refusal).
