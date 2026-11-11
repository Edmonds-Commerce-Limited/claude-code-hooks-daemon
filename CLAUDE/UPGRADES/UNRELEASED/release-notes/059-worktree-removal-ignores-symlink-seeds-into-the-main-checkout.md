# Fix: removing a worktree no longer blocks on a symlink seed that points at the main checkout

**Plan**: none (client report)
**Audience**: client projects

`git worktree remove` was denied by R-GIT-WORKTREE-REMOVE-FORCE ("holds 1 path(s) the removal would lose") when the only content of an ignored directory in the worktree was a `worktree_create` symlink-mode seed. The rule already recognised a copy-mode seed identical to its source, but not a link whose target is the main checkout's own file, and removing such a link loses nothing.

A symlink inside an ignored directory now counts as losing nothing when it resolves to an existing path inside the main checkout and outside the worktree being removed. A dangling link, a link pointing elsewhere, a link into the worktree itself, and any real file beside the link still protect the directory, so the denial is unchanged for them.

The merged-branch cleanup after a pull-request merge is a separate matter: `branches.default` (or `branches.integration_lines`) must name the real integration branch for the daemon to treat a merge into it as safe. See the `branches:` block in your `.claude/hooks-daemon.yaml`.
