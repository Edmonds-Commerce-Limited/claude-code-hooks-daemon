# Callout: the worktree events get a budget longer than their git call

**Plan**: 00512
**Audience**: everyone

A `git worktree add` that took more than about 20 seconds, for example behind a slow `post-checkout` hook, used to get no path back: the chain deadline (20s) and the client's socket wait (30s) were both shorter than the handler's own 30s git budget, so Claude Code saw a failed worktree creation while git went on to create the worktree and branch as orphans. WorktreeCreate and WorktreeRemove are not guards, so they now have their own budget in `Timeout.EVENT_HANDLER_BUDGET`, `EVENT_CHAIN_DEADLINE` and `EVENT_CLIENT_WAIT`: the chain deadline is 55s for create and 65s for remove, and the client (`init.sh` and the relay forwarder) waits 60s and 70s. A failed or timed-out add is also undone: the worktree and the branch that call created are removed, and a branch that already existed is left alone. Every guard event keeps the 20s deadline, and `daemon.chain.deadline_seconds` still sets it (reported as issue #82).
