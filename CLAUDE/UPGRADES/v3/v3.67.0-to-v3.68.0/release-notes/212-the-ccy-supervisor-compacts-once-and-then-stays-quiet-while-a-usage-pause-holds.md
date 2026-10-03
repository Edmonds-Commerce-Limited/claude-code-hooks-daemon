# Callout: the ccy supervisor compacts once, then stays quiet, while a usage pause holds

**Plan**: 00479
**Audience**: operators

A session paused on its usage ceiling is meant to sit idle until its resume
cron fires at the window reset. The supervisor used to know nothing of that and
would have nudged it awake with `continue` or `/goal`. The daemon now records a
pause as a `<session>.usage-paused` file beside the other supervisor signals
(`claude_code_hooks_daemon.utils.usage_pause` writes, reads and clears it).

While a live record exists for the session, the supervisor waits for the
session to stop and types exactly one `/compact`. Its instruction gives the
resume time in UTC and says to do nothing until the resume cron fires, so
resuming does not pay the uncached-context penalty of a large conversation. It
types nothing else: no `continue`, no `/goal`, no model restore or reminder.
When the record is cleared, or expires an hour after the resume time, it
behaves as before. An unreadable record counts as no pause.

The rule ships by the worker hot-reload, with no session restart. The record is
written by the daemon's usage gate, which is separate work. See
`CLAUDE/development/CcySupervisor.md`.
