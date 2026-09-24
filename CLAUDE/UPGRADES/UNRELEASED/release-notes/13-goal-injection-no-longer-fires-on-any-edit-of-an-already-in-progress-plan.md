# Callout: `goal_injection` and `recovery_cron_advisor` no longer fire on any edit of an already-terminal-status plan

**Plan**: 00466
**Audience**: operators

`goal_injection` (the ccy PTY supervisor's `/goal`-setting sensor) matched
the post-write STATE of a plan's `**Status**` line, not a TRANSITION to it,
so the first Write or Edit in a session to any plan that was already In
Progress fired — a table-row addition, a task tick, a typo fix. That
spuriously ledgered the touched plan as owed work, could displace a
genuinely live plan's `/goal` condition with a "GOAL DISPLACED" advisory,
and had the Stop hook challenge stops on the spuriously ledgered plan's
behalf. `recovery_cron_advisor`'s Write-path completion check had the same
defect shape for `**Status**: Complete`: rewriting an already-complete plan
re-injected the CronDelete teardown advisory every time. Both now fire only
when the triggering Write/Edit is itself what moved the Status line;
`goal_injection` reads its own Edit's replaced span or (for a Write) git
HEAD, and `recovery_cron_advisor`'s Write path shares that same HEAD
comparison. An edit or rewrite that leaves an already-In-Progress or
already-Complete status unchanged emits nothing from either handler. No
action is needed — this only removes false triggers.
