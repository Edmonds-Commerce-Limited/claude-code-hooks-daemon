# Callout: scratch sweep never gives a git object store the short hold, and closes the Task 3.9 review findings

**Plan**: 00627
**Audience**: operators

`scratch-sweep` no longer judges a scratch entry DISPOSABLE when it holds a git repository with objects. A clone made with `git clone --shared` anywhere on disk borrows a repository's objects through its `alternates` file, and no sweep can find such a borrower outside the project. Such an entry is now UNCERTAIN: `--apply` packs it with the 168-hour hold (`scratch.archive.uncertain_hours`) rather than the 12-hour one, and prints its restore command as before. A clone that broke when its lender was archived can be repaired with `hooks-daemon scratch-sweep restore <id>` within that hold. Entries with no repository, or holding only an empty one, are unchanged. When a git pointer in the scratch root cannot be read, an UNCERTAIN entry is now held STUCK, as a DISPOSABLE one already was.
