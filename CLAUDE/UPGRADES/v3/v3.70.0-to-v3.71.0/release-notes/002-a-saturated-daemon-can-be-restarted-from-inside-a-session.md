# Callout: a saturated daemon can be restarted from inside a session

**Plan**: 00533
**Audience**: operators

When many concurrent sessions filled the daemon's dispatch pool, every PreToolUse call was denied as "dispatch pool saturated", including the exact `hooks-daemon restart` command that would have cleared it; that command is now judged without needing a slot of the shared pool (and the hook client lets it through a saturation deny from an older daemon), and a stop under load no longer escalates to SIGKILL, because the SIGTERM grace (8s) now outlasts the daemon's 5s drain of in-flight requests. The pool size is configurable as `daemon.chain.max_inflight` (default 16, unchanged), a full pool now waits `daemon.chain.slot_wait_seconds` (default 2s) for a slot before refusing, and saturation lasting 10s or more is logged as a WARNING naming its duration, repeated at most every 30s. Stop and SubagentStop still fail closed under saturation. (reported as issue #124)
