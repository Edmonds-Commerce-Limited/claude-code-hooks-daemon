# Callout: a finished subagent is no longer told to create the coordinator's crons

**Plan**: 00470
**Audience**: operators

`cron_subagent_stop_enforcer` denied a subagent's stop whenever the session reported no matching cron, telling the subagent to run `CronCreate`. Session crons belong to the coordinator's session, so a subagent could never legitimately satisfy that, and each such stop was denied for nothing. The handler is now scoped to the main thread, like `cron_stop_enforcer`, so a real subagent stop is never judged by it; the coordinator's own `Stop` still enforces every declared `persistent_crons` job. A project that wants the old behaviour can set `scope: ALL` on the handler (reported as issue #62).
