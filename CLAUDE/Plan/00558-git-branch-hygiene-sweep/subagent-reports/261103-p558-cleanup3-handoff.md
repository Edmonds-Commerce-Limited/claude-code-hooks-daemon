# Handoff: Plan 00558 Task 3.1, third agent (steps 2a and 2b built; handler, CLI and wrap-up left)

Brief: `/workspace/untracked/scratch/brief-558-cleanup-3.md` (its coordinator rulings override
`261103-p558-cleanup2-handoff.md`). Worktree `/workspace/untracked/worktrees/worktree-558-cleanup`,
branch `worktree-558-cleanup`, head 998a6fc07 plus this handoff's commit, pushed. Stopped at the
soft context budget.

## Done (committed, tests green, mypy strict and ruff clean)

- 80b390744 `daemon/branch_safety.py`: `classify_branch(..., ignore_worktree=False, content_tier=True)`; `delete_branches(..., content_tier=True)` passes it through. Tests in
  `tests/unit/daemon/test_branch_safety.py::TestCleanupKeywords`.
- 998a6fc07 `core/branch_cleanup.py` (99.6% branch coverage,
  `tests/unit/core/test_branch_cleanup.py`, 48 tests). Public API:
  - `cleanup_after_merge(repo, names, *, config, target, mode) -> CleanupReport`: the hook's
    whole job. Merged tiers only, `bundle_path=None`, restore line `git branch <name> <sha>`;
    worktree-held branch is advised (`git worktree remove <path>` + delete-branch command), never
    removed; patch-equivalent prints `bin/hooks-daemon branch-sweep --clean`; remote delete
    printed when `refs/remotes/<remote>/<name>` exists.
  - `clean_sweep(repo, config, *, dry_run, bundle_dir) -> CleanupReport`: inventory candidates
    (merged, merged-into-line, patch-equivalent, local tip), each classified alone, worktree
    removed only when `worktree_blockers()` is empty (no `--force`, `GIT_WORKTREE_REMOVE`),
    then one `delete_branches` batch with bundle `bundle_dir/branch-cleanup-<UTC stamp>.bundle`.
    Raises `BranchInventoryError` / `ValueError` (no default branch).
  - `merge_target_qualifies(target, config, default)`, `policy_refusal`, `cleanup_targets`,
    `worktree_blockers`, `is_regenerable`, `render(report) -> list[str]`, `SWEEP_CLEAN_COMMAND`.

## Deviation to report

`ls-files --others --ignored --exclude-standard --directory` collapses a WHOLLY ignored
`untracked/` to one entry, which would hide the regenerable stores. `_expand` lists that one
directory's children (Python `iterdir`, one level) and judges each. Still one git call.

Finding for the coordinator: in this repository's real worktrees the ignored listing also holds
`.claude/hooks-daemon/`, `src/*.egg-info/`, `untracked/.venv-bootstrap*`, `untracked/lsp-venv`,
`untracked/.python-cmd-cache`, `untracked/repair.log`. None is on the ruling's regenerable list,
so `--clean` will skip every real agent worktree here until the list grows.

## Left

1. Handler `handlers/post_tool_use/cleanup_after_merge.py`: match Bash `git merge` (not
   `--squash/--abort/--continue/--quit`), operands via `utils/git_commit_parsing.git_invocations`
   (skip `-m/-s/-X` values), place with `utils/merge_scope.merge_directory`, target = current
   branch of that checkout, require `merge_target_qualifies`, call `cleanup_after_merge` with
   `config.branches.cleanup_after_merge.mode`, return `render()` lines as context. Model:
   `daemon_sync_after_merge.py` (HandlerID, Priority, registry, `get_claude_md`, acceptance test
   with `harness_cannot_produce`, handler entry in `.claude/hooks-daemon.yaml` if required).
2. CLI: `--clean` and `--dry-run` on `branch-sweep` (`cmd_branch_sweep` ~`daemon/cli.py:6489`,
   parser ~12923) calling `clean_sweep(repo, branches, dry_run=..., bundle_dir=repo / "untracked/branch-cleanup")` and printing `render()`.
3. Wrap-up per the brief: report `261103-task31-cleanup.md`, release note 025, manifest if a
   key changed (none so far), `branches: {cleanup_after_merge: {mode: act}}` in this repo's
   `.claude/hooks-daemon.yaml`, journal via `mkplan.bash --journal 558 action`, targeted QA.
