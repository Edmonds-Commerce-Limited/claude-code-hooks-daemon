# Callout: WorktreeRemove and other hard-failing git calls now wait longer on a loaded host

**Plan**: 00474
**Audience**: client projects

`git worktree remove` inside the WorktreeRemove event ran on a fixed 30 s budget. On a host at a load average near 70 that killed the removal part way and left a half-deleted `prunable` worktree. The removal now runs on a 30 s base scaled by host load, bounded by a 120 s ceiling, and the handler's other git calls (worktree list, containment check, creator record, merge probe, prune) are scaled the same way as the WorktreeCreate metadata calls, up to 10 s each.

Behaviour change: the WorktreeRemove event budget grows from 60 s to 170 s, and the client wait that mirrors it (`init.sh` `_event_socket_wait`, the relay guard) from 70 s to 180 s. An idle host is unaffected: every base is the floor and scaling only lengthens a budget.

Upgrade: nothing to do; the next converge or upgrade rewrites `init.sh` and the relay wrapper with the new wait.
