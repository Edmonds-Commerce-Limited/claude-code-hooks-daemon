# Callout: scratch sweep never gives a git object store the short hold, and closes the Task 3.9 review findings

**Plan**: 00627
**Audience**: operators

`scratch-sweep` no longer judges a scratch entry DISPOSABLE when it holds a git repository with objects. A clone made with `git clone --shared` anywhere on disk borrows a repository's objects through its `alternates` file, and no sweep can find such a borrower outside the project. Such an entry is now UNCERTAIN: `--apply` packs it with the 168-hour hold (`scratch.archive.uncertain_hours`) rather than the 12-hour one, and prints its restore command as before. A clone that broke when its lender was archived can be repaired with `hooks-daemon scratch-sweep restore <id>` within that hold. Entries with no repository, or holding only an empty one, are unchanged. When a git pointer in the scratch root cannot be read, an UNCERTAIN entry is now held STUCK, as a DISPOSABLE one already was.

After a restore, a sweep that crashed while claiming the restored entry no longer removes it on the strength of the archive made before the restore: resuming a leftover claim accepts only an archive packed after that claim was recorded, and otherwise renames the entry back.

An entry holding a file or directory with a `user.*` extended attribute, or a sparse file (one with holes), is no longer archived or removed: the sweep reports it refused and leaves it in place. The archive format keeps neither, so a restore would have dropped the attribute or written the holes out as zeros, and the archive check could not see either loss. The same holds when the attribute list or the holes cannot be read. The check runs again just before removal. Archives recorded before this change are not checked again.

`worktree-reap --reap` now reads a worktree's blockers again as the last step before `git worktree remove`, inside the function that runs the removal. A plain remove deletes ignored files, so a scratch note written into the worktree after the earlier check would have been deleted unarchived; it now keeps the worktree, reported as `KEEP` with the paths it would lose. This narrows the window rather than closing it: a file written between that last read and git's delete is still lost.

`scratch-sweep --apply` now treats an entry as in use when any process holds a file inside it open, through a descriptor or a memory map, not only when a process's working directory is inside it. A process whose descriptor table or map cannot be read makes every entry in use, as an unreadable working directory already did.

`scratch-sweep --apply` run in a linked worktree no longer expires any archive. Both checkouts record their entries under the same `untracked/scratch` path, so a linked run judged the main checkout's archives by the worktree's own claims and references, and could expire one the main checkout still referred to. It now says on stderr that expiry runs only from the main checkout. A run in the main checkout still expires archives packed from a worktree, judged by the main checkout's claims and references; that is unchanged.
