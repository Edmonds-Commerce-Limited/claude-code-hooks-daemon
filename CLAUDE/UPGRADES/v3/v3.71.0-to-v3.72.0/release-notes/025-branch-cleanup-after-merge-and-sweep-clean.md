# Callout: a merged branch is cleaned up after the merge, and `branch-sweep --clean` deletes the rest behind a bundle

**Plan**: 00558
**Audience**: operators

A new PostToolUse handler, `cleanup_after_merge`, runs after a `git merge` into the default branch or an integration line. Each local branch named on the merge command is handled per `branches.cleanup_after_merge.mode`. The default `advise` prints the `bin/hooks-daemon delete-branch` command. `act` deletes the branch when the target holds every one of its commits and prints `git branch <name> <sha>`, the line that restores it. `off` is silent. It never removes a worktree: a branch checked out in one gets the `git worktree remove` and delete commands printed for you to run. A patch-equivalent branch is not deleted after a merge; it is pointed at `branch-sweep --clean`. The remote delete is printed, never run. A `--squash`, `--no-commit`, `--abort` or `--continue` merge is ignored.

`bin/hooks-daemon branch-sweep --clean` deletes every merged and patch-equivalent local branch in one batch, behind a recovery bundle under `untracked/branch-cleanup/`, and prints the `git fetch <bundle> ...` line that restores each branch. A linked worktree holding one of those branches is removed first, without `--force`, and only when it is clean and every ignored path in it matches `branches.cleanup_after_merge.regenerable`. That list defaults to the venvs, QA output, caches, `.claude/hooks-daemon/`, `*.egg-info/`, `untracked/.venv-bootstrap*` and `untracked/lsp-venv/`. `untracked/scratch/` always blocks the removal, and a config list that would cover it fails the load. `--clean --dry-run` prints what would happen and changes nothing.

On upgrade: run `bin/hooks-daemon branch-sweep --clean --dry-run` to see what a clean would remove. Set `branches.cleanup_after_merge.mode: act` when you want merged branches deleted automatically. If your worktrees hold other rebuildable ignored stores, add them to `regenerable`.
