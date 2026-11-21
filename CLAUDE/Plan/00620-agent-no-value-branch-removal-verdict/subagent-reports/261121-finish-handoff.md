# Plan 00620 close-out handoff (branch plan-00620-finish)

## Status per open item

- **Task 3.1**: done. Follow-up filed as Plan 00629 (`recovery-copy-advisory-reject-route`),
  commit aded8b33f. Dedupe: no live plan mentions `recovery_copy_advisory`; Plan 00594 Task 4.8
  wrote the `refs/archive/` practice and is done, it does not cover the change.
- **Success Criteria 1-4**: ticked with test names (163 tests passed on origin/main code,
  2026-11-21, files listed in PLAN.md). A second Q1-class accepted residue (keep verdict flipped
  with its keep record deleted, pinned by
  `test_accepted_residue_a_keep_flipped_with_its_keep_record_removed_is_not_caught`) was not in
  Known gaps; it is now. Nothing was loosened.
- **Independent loosening review**: NOT ticked. Signed off up to 09e1512e3 (F-BYPS re-check "fit to
  merge", D-EXEC re-check "no findings"). Two delete-path commits merged after that range were
  never reviewed: 8260463ff and 09e744603. Both add refusals only, but the sign-off must cover the
  merged code. Dispatch the two briefs below (security-reviewer takes ONE check id per dispatch).
- **CI green**: NOT ticked; see the CI section.
- **Archive**: not done, because the two items above are open.

## Reviewer brief 1 (subagent_type: security-reviewer, model: opus)

> Check `D-EXEC`. Plan 00620 (agent no-value branch removal). Repository: a worktree of
> origin/main at or after b3ac2c7b7. Interval: the two commits 8260463ff ("refuse a branch a
> rebase or bisect holds in any worktree") and 09e744603 ("branch_safety.\_read_state_file
> error_hiding finding"); read `git show 8260463ff 09e744603 -- src`. Scope:
> `src/claude_code_hooks_daemon/daemon/branch_safety.py` `_read_state_file`,
> `_operation_holding_branch` and their caller before `_delete_rejected`. Hunt: every git
> spawn goes through `run_git` with a list argv; the `--git-common-dir` lookup, admin-dir paths
> (`worktrees/*`, `rebase-merge/head-name`, `rebase-apply/head-name`,
> `rebase-merge/update-refs`, `BISECT_START`) cannot be steered by a branch name or a file
> content into another path or an option. Reply inline with verdict, findings with file:line,
> class, why tests miss it, detector hypothesis. Read-only.

## Reviewer brief 2 (subagent_type: security-reviewer, model: opus)

> Check `F-BYPS`. Plan 00620. Same interval and files as above (8260463ff, 09e744603). The
> route deletes a branch with `git update-ref --no-deref -d refs/heads/<name> <tip>`, which,
> unlike `git branch -D`, does not refuse a branch another worktree holds; these commits add the
> refusal for a branch held by an in-progress rebase or bisect. Hunt: any state in which a branch
> another worktree is rebasing, bisecting or otherwise holding is still deleted (rebase backends,
> `--update-refs`, a linked worktree whose admin dir is unreadable or missing, a `head-name`
> with trailing whitespace or no `refs/heads/` prefix, a main-worktree operation); any read
> failure that answers "no operation" instead of refusing. `FileNotFoundError` meaning "no
> operation" is by design; anything else must refuse. Run
> `tests/unit/core/test_branch_reject_delete.py::TestOperationInProgress`. Reply inline with
> verdict and findings as above. Read-only.

On two clean verdicts: tick "Independent loosening review" in PLAN.md citing the two reports.

## CI

`gh run list --branch main` at close-out: QA run 44854305236 and CodeQL 44854305519 for merge
commit 69e375788, and the runs for 8309b2d5c and b3ac2c7b7, were in progress. The two previous
main QA runs (bcc88e01a, 3abec620a, before the merge) failed. Tick "CI green" only on a
`success` QA conclusion for a main commit that contains 69e375788.

## To archive once both are ticked

Flip Status to Complete, tick Task 2.4, `git mv` the folder into `Completed/`, move the README
row (keeping 30 completed rows), update statistics, journal via `mkplan.bash --journal`, all in
one commit. The release note 014 already satisfies R-PLAN-DONE-HOLDING-AREA (Success
Criterion 4).
