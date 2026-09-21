# Callout: handlers can declare whether they run for the coordinator, subagents, or both

**Plan**: 00423
**Audience**: everyone

Any handler may now declare `scope: ALL | MAIN | SUB`, and `ALL` stays the
default so nothing changes unless you set it — the role is decided by whether
the event carries a subagent id, never by guesswork. This closes a reported
problem where a finished subagent was told, on every failsafe tick, to continue
plans from the coordinator's goal ledger that were never its assignment; the
three stop-time nudges where only a coordinator can act now ship scoped to the
coordinator. Relatedly, a subagent can no longer delete a session cron — the
incident behind the report was one deleting a shared recovery cron to stop the
nudges, leaving a live session with no recovery path — so if you disabled a stop
handler outright to work around this, you can stop doing that and scope it
instead.
