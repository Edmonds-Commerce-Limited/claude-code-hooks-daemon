# Callout: a worktree add on a heavily loaded host is given longer, and a timed-out one is cleaned up and explained

**Plan**: 00474
**Audience**: client projects

Creating a worktree for an `isolation: "worktree"` agent or a `--worktree` session used to give `git worktree add` a fixed 30 seconds. On a host busy with something heavy, such as a QA run, git needed longer, the creation was denied as a handler crash, and the cleanup, on 5-second calls of its own, could not remove the half-populated checkout directory it left behind. That directory had no registered worktree and no branch, so `git worktree remove` did not know it.

The add now runs on a budget scaled to host load: the 30-second base on an idle host, growing with the load average per CPU up to a ceiling of 120 seconds. The cleanup calls scale the same way, up to 10 seconds each. If the add still times out, the handler undoes it, deleting the partial directory itself when git does not own it, and the deny names the cause, the load average and the safe action, which is to retry once the load drops. The timeout and the load average are also logged as a warning. The slowest case the event can now take is longer, so the `WorktreeCreate` client wait in `init.sh` moves from 90 to 230 seconds; the hook is registered without a short timeout, so nothing else changes. `worktree remove` in `branch-sweep --clean` and `worktree-reap` scales its 300-second budget the same way, up to 20 minutes.

A new QA check, `fixed_worktree_budget`, fails the build when a function that writes a worktree runs a git call on a fixed budget.
