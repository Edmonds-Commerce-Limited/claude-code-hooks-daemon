# Callout: a declared cron is refreshed before its 7-day expiry

**Plan**: 00470
**Audience**: operators

Recurring Claude Code crons die 7 days after creation. In an always-on session whose declared jobs were created together they all die together, and since a cron tick is the only thing that produces a Stop, nothing was left to notice. A new default-on `cron_record_keeper` handler now records when each `CronCreate` happened, and `cron_stop_enforcer` (and its `SubagentStop` twin) denies a stop while a live declared job is older than `options.refresh_after_days` (default 6), naming the `CronDelete` and `CronCreate` that refresh it. A job the daemon has no record of is stamped at its next Stop rather than denied, so the first refresh after upgrading can come up to 6 days late. A teammate or sub-agent stop was checked and never writes the lead's `[awaiting-human]` marker; a regression test now pins it.
