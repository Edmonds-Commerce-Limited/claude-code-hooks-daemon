# Callout: the supervisor can compact on its own at a true idle once context reaches 30 percent

**Plan**: 00603
**Audience**: client projects

The ccy supervisor used to compact only when the context reached the RED tier. It can now also inject ONE armed `/compact`, followed by the usual post-compaction `continue`, when the session is in a true idle and the context is at or above a percentage you choose (default 30). This supplements Claude Code's own `idleCompaction`, which waits about an hour and needs the one-hour prompt cache; the daemon's optimal-config check and SessionStart sync for `idleCompaction` are unchanged.

A true idle means: the screen shows the main prompt, its footer names no background task, sub-agent, shell or running turn, the input box is empty, the focus hold is clear, nothing is streaming, no injection is pending, and that state has held for a settle period (default 60 seconds). A cooldown after any compaction (default 30 minutes) and an absolute token floor (default 100000) stop a small window being compacted at 30% of nothing. The RED and CRITICAL tiers and the status-line colours are unchanged.

**Default for clients: `dry-run`.** Nothing is typed; each time the trigger would have fired, `decision.log` gets a `would idle-compact` line with the percentage and token count. That gives you the firing rate before the behaviour, and a `/compact` rewrites context, so it is armed only on request. Set `CCY_IDLE_COMPACT=on` in `.claude/ccy/ccy.env` to arm it (the supervisor's own dry-run, when it is not started with `--arm`, still types nothing), or `off` to remove it.

Tunables, all optional: `CCY_IDLE_COMPACT_PCT`, `CCY_IDLE_COMPACT_SETTLE_SECONDS`, `CCY_IDLE_COMPACT_COOLDOWN_SECONDS`, `CCY_IDLE_COMPACT_MIN_TOKENS`. See [CLAUDE/development/CcySupervisor.md](../../../development/CcySupervisor.md).

The "no background task or sub-agent" test reads the footer of the rendered screen, because no sidecar or hook signal reports either; it needs the `hooks-screen` binary and fails closed (never fires) without it. The host half (the screen read) takes effect on the next ccy relaunch; the decision half hot-reloads with the worker.
