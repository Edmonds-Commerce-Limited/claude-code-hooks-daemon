# Callout: the supervisor's idle compaction now keys on the orange context tier after ten minutes idle

**Plan**: 00603
**Audience**: client projects

The ccy supervisor's own idle compaction (shipped in dry-run by default) changed its two main defaults. It now fires when the session's context tier is ORANGE or higher, instead of at a fixed 30 percent, and only after the true idle has held unbroken for 600 seconds, instead of 60. The tier is the daemon's own classification, the same one the status line colours, so the gate follows the window size: orange starts at 30 percent of a 1M-token window and 51 percent of a 200k one. A 200k session at 35 percent (yellow) is therefore no longer a candidate, and a 1M session behaves as before apart from the longer wait.

New setting `CCY_IDLE_COMPACT_TIER` (`yellow`, `orange` or `red`; anything else is `orange`). `CCY_IDLE_COMPACT_PCT` is now unset by default; setting it replaces the tier gate with that percentage, so a project that pinned a percentage keeps it. A sidecar tier the supervisor does not recognise never fires.

The idle compaction also now waits for queued supervisor work: when a standing-authorisation reminder, a session-actions directive or a cron-reconcile prompt is pending, that goes first and the compaction is reconsidered after.

The mode default is unchanged (`dry-run`: a `would idle-compact` line in `decision.log`, nothing typed); set `CCY_IDLE_COMPACT=on` in `.claude/ccy/ccy.env` to arm it. The decision half hot-reloads with the worker; no relaunch is needed for the new defaults. See [CLAUDE/development/CcySupervisor.md](../../../../development/CcySupervisor.md).
