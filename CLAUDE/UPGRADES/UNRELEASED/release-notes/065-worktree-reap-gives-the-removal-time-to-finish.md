# Callout: worktree-reap gives the removal time to finish and no longer calls a failure a dry run

**Plan**: 00474
**Audience**: client projects

`hooks-daemon worktree-reap --reap` ran `git worktree remove` under the 5 second timeout meant for git metadata queries. Removal deletes the whole tree, and an agent worktree carries its own venv, so git was killed mid-delete. That left a half-deleted worktree with its `.git` file already gone, which git then refused to remove ("validation failed"). The removal now has its own limit (`Timeout.GIT_WORKTREE_REMOVE`, 300 seconds). If even that is exceeded, the report says the removal was interrupted and may be partial, and names the recovery: `git worktree prune`, then `git branch -d <branch>`.

The same command printed `DRY-RUN` for any worktree it did not remove, including a git refusal or failure under `--reap`. Under `--reap` that line now reads `FAILED`; a run without `--reap` still reads `DRY-RUN`. The safety contract is unchanged: removal never uses `--force` and the branch delete never uses `-D`.
