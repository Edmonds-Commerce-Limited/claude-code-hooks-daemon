# Callout: WorktreeRemove no longer force-removes a worktree, and deletes its branch once merged

**Plan**: 00558
**Audience**: operators

The `worktree_remove` handler used to run `git worktree remove --force` on the path Claude Code named, which deleted every ignored file in it, `untracked/scratch/` notes included (#155), and it never deleted the branch. It now:

- removes only a path `git worktree list` names as a linked worktree, and only when nothing would be lost: no modified or untracked file and no ignored path outside `branches.cleanup_after_merge.regenerable`. Otherwise the worktree is left and the blocking paths are written to the daemon log;
- adds `--force` only when the worktree's HEAD is also held by another ref;
- then deletes the branch when it has the WorktreeCreate `<slug>-<8 hex>` name and the default branch or an integration line holds every commit, logging the `git branch <name> <sha>` restore line. Any other branch is left for `bin/hooks-daemon branch-sweep --clean`;
- skips and logs the remaining steps when its event budget runs out.

`worktree-reap`'s orphan pruning now also covers `<slug>-<8 hex>` branches, not only `agent-*`.

`branch-sweep --clean` and this handler share three fixes found by running the sweep on this repository: an empty directory (an empty `untracked/scratch/` included) is never a blocker, a `store/` glob also matches a symlink of that name (`untracked/lsp-venv`), and the `regenerable` default now lists `untracked/repair.log`, `untracked/repair.txt`, `.coverage`, `untracked/.python-cmd-cache`, `untracked/context-sidecar/`, `untracked/logs/`, `untracked/acceptance/` and `.CLAUDE.md.pre-inject`.

The SessionStart branch summary again names, on a new session, each work branch more than `branches.sweep.behind_threshold` (default 50) commits behind the default branch, within its existing line cap.

Nothing to do on upgrade.
