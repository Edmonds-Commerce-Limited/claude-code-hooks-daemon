# Callout: `goal_injection` no longer fires on any edit of an already-In-Progress plan

**Plan**: 00466
**Audience**: operators

`goal_injection` (the ccy PTY supervisor's `/goal`-setting sensor) matched
the post-write STATE of a plan's `**Status**` line, not a TRANSITION to it,
so the first Write or Edit in a session to any plan that was already In
Progress fired — a table-row addition, a task tick, a typo fix. That
spuriously ledgered the touched plan as owed work, could displace a
genuinely live plan's `/goal` condition with a "GOAL DISPLACED" advisory,
and had the Stop hook challenge stops on the spuriously ledgered plan's
behalf. The handler now fires only when the triggering Write/Edit is itself
what moved the Status line to In Progress; an edit that leaves an
already-In-Progress status unchanged emits nothing. No action is needed —
this only removes false triggers.
