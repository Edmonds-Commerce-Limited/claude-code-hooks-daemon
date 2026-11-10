# Callout: a seeded copy identical to its source no longer blocks a worktree removal

**Plan**: 00579
**Audience**: client projects

The worktree-removal check (`R-GIT-WORKTREE-REMOVE-FORCE`, also used by `branch-sweep --clean` and the `WorktreeRemove` handler) now reads the `worktree_create` seed list directly. A copy-mode seeded file, or a seeded directory, that is byte-identical to its source in the main checkout can no longer be lost, so it no longer blocks the removal and needs no `branches.cleanup_after_merge.regenerable` entry. A copy that differs from its source, or whose source is gone, still blocks, and the deny names it as differing from its source. Symlink seeds, `regenerable` globs (which add to the seed list) and every other ignored entry behave as before. If you repeated seed paths in `regenerable` only to get past this, you can remove them.
