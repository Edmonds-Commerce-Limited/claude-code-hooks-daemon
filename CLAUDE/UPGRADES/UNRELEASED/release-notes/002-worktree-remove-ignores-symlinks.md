# Callout: removing a worktree no longer refuses over a seeded symlink

**Plan**: 00474
**Audience**: client projects

The `git worktree remove` guard (R-GIT-WORKTREE-REMOVE-FORCE) used to list an ignored symlink, such as a file the `worktree_create` handler seeds with `default_mode: symlink`, as content the removal would lose. That refused to remove a clean, merged worktree. A symlink is now never counted: removal only unlinks it and its target outside the worktree survives. Real ignored files and non-empty ignored directories still block as before.
