# Callout: `worktree-reap --reap` can archive a worktree's scratch, at a terminal only

**Plan**: 00627
**Audience**: everyone

A worktree kept only because it holds scratch notes under `untracked/scratch/` can now be reaped without losing them. Run `hooks-daemon worktree-reap --reap --only <name>` from the main checkout at a terminal: when every entry is safe to archive, it asks you to type `evacuate <worktree path>`, packs each entry into the main checkout's archive store (printing its `scratch-sweep restore` command), and then removes the worktree and its branch as before. Nothing else can do this: with no terminal, a wrong phrase or the housekeeping step `worktree-reap-reap`, the worktree is kept and the command is named. Any entry that is protected, kept, referenced, live or unreadable keeps the whole worktree with nothing packed. Only root-level entries are evacuated: a worktree whose scratch holds a session directory (`s-*`) is kept, and you file or delete its contents by hand.

After a `git merge`, `cleanup_after_merge` now names that command instead of `git worktree remove` when the worktree holding the merged branch has scratch. It removes and packs nothing.
