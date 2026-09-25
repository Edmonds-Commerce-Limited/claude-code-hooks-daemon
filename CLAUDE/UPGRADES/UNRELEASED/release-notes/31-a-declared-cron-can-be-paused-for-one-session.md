# Callout: a declared cron can now be paused for one session

**Plan**: 00422
**Audience**: operators

`hooks-daemon cron-pause <job> --reason "..."` pauses one `persistent_crons`
job for the current session only. While the pause is live,
`cron_stop_enforcer` and its SubagentStop twin accept that job as missing
instead of blocking every stop. Every stop that finds it missing names the job,
the reason and the expiry, and `persistent_cron_assertor` stops asking for it
within that session. The pause expires within 24 hours on its own, and
`hooks-daemon cron-resume <job>` ends it early. An id that names no active
declared job is refused. `persistent_crons` in `.claude/hooks-daemon.yaml`
remains the only permanent off switch, and the next session is asked to create
the job again.
