# Callout: the ccy supervisor reminds a long-quiet session to rebuild its expired crons

**Plan**: 00470
**Audience**: everyone who runs `ccy`

A session cron lives at most seven days, and the Stop-hook refresh only runs while Stop hooks fire. A session that has been silent for hours with every recorded cron already past its expiry would therefore stay without its scheduled jobs. The supervisor now types one reconcile prompt in that case, the same "Run CronList FIRST, then re-create what the project declares" wording as the `persistent_cron_assertor` SessionStart message.

- It fires only when `cron-records.json` holds at least one record for this session, every one is at least seven days old, and the child has produced no output for two hours (PTY quiet stands in for "no hook traffic"). A missing or malformed file never fires it.
- It is the last built-in injection family, below session-actions. It respects the usage pause, the empty-input-box guard and an unconfirmed own line. It repeats at most once per quiet window and at most ten times per supervisor process.
- The supervisor only reads the record file. The seven-day expiry, file name and field names are copies pinned to `utils/cron_records.py` by a test.
- To take effect, restart the supervisor at a convenient moment: the host now measures the child's output quiet time, and that measurement is host code, which a worker hot-reload does not replace. Until then the watchdog stays silent.
