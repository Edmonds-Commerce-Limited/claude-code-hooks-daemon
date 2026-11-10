# Callout: a refused park push is kept for a remote-only branch too, stops counting as open, and an ended park is announced

**Plan**: 00594
**Audience**: client projects

Three gaps left by the earlier `branch-park` change are closed.

1. **A branch only the remote holds** now behaves like a local one when the push is refused. `hooks-daemon branch-park <name> --reason ...` keeps the park in a new local branch at the park commit, writes the same git-config record, prints `WARNING: parked locally, not pushed` with git's reason and `git push <remote> <name>`, and exits 3. A push that succeeds still leaves no local branch.
2. **A rejected park push no longer counts as open work.** When the local park record still holds and the remote copy sits behind the park commit, the branch is counted in the parked pool, not the open one, so it stops filling `branches.wip.cap`. A remote tip that is not behind the park keeps the branch open.
3. **A park that ends is announced.** When a branch gains new work or its ref disappears, the next session start and the next `hooks-daemon branch-sweep` print `Park cleared: <name> (<reason>)` once, and the record is then removed. A merge keeps printing the same line as before.
