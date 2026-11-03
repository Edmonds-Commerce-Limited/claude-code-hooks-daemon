# Task 3.1 report: cleanup after merge and `branch-sweep --clean`

Four agents built this on branch `worktree-558-cleanup` (handoffs `261103-p558-cleanup*-handoff.md`).

## Steps

- **Step 0-1** (agents 1 and 2): the design was settled in the handoffs. Two callers share one module, so they cannot disagree about what is safe.
- **Step 2a** (80b390744): `classify_branch(..., ignore_worktree, content_tier)`. The cleanups classify a branch held by a worktree they judge separately, and they skip the content-preserved tier (a walk of every reachable object).
- **Step 2b** (998a6fc07): `core/branch_cleanup.py` holds `cleanup_after_merge`, `clean_sweep`, `worktree_blockers` and `render`.
- **Step 3a** (29b5306e0): the regenerable list became the config key `branches.cleanup_after_merge.regenerable`. Its matcher is `utils/regenerable_paths.py`, a gitignore-style subset. It lives in `utils` so the config model can validate against it without an import cycle.
- **Step 3b** (8a5d1b871): `handlers/post_tool_use/cleanup_after_merge.py` runs at priority 39. This repository sets `mode: act`.
- **Step 3c** (de909955d): `branch-sweep --clean [--dry-run]` writes its bundle to `untracked/branch-cleanup/`. Exit codes: 0 when the sweep ran, 1 when it could not run, 2 on flag misuse (`--dry-run` without `--clean`, or `--clean` with `--json`/`--all`).

## Rulings applied

- **Bundles**: the hook writes none. Bundling one branch took 8.2 s and 51 MB, which no hook budget absorbs. The hook deletes only the merged tiers, whose every commit the target holds, and prints `git branch <name> <sha>`. `--clean` deletes the merged and patch-equivalent tiers in one `delete_branches` batch behind one bundle, and prints a `git fetch <bundle> refs/heads/<n>:refs/heads/<n>` line for each branch.
- **Worktrees**: the hook never removes one, because `git worktree remove` deletes ignored files (issue #155). It prints the removal and delete commands instead. `--clean` removes a linked worktree without `--force`, and only when `worktree_blockers()` is empty: no dirty or untracked file, and every ignored entry matches the regenerable list.
- **Regenerable list**: the model default is the original list plus `.claude/hooks-daemon/`, `*.egg-info/`, `untracked/.venv-bootstrap*` and `untracked/lsp-venv/`. `untracked/scratch/` always blocks. A list containing a blank entry, or one that would cover `untracked/scratch/` (for example `untracked/`, `untracked/*/`, `*` or `scratch/`), fails the config load. A wholly ignored `untracked/` is listed one level deep (`_expand`), as accepted.

## Handler details

The handler acts only on a concluding `git merge` with git in command position: `--squash`, `--no-commit`, `--abort`, `--continue` and `--quit` are ignored. It skips the values of `-m`, `-s`, `-X`, `-F` and their long forms. It places the merge with `merge_scope.merge_directory`, so `git -C` and `cd` count. The target is the branch checked out there and must be the default branch or an integration line. Only operands that are local branches are judged, so a sha or a remote ref is ignored. If git fails during the cleanup, the context says so and nothing is deleted.

## Not done here

PLAN.md ticks and DESIGN.md edits are left to the coordinator, as the brief instructed.
