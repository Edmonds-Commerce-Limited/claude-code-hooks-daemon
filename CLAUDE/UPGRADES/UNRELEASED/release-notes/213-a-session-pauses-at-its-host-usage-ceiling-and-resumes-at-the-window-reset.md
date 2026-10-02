# Callout: a session pauses at its host usage ceiling and resumes at the window reset

**Plan**: 00479
**Audience**: operators

A host whose `hosts:` entry sets a `usage_ceiling` now pauses a session when a
usage window reaches it, instead of letting the session run into the account's
hard limit. The pause does not end the session:

- The prompt that trips the ceiling carries a directive: `CronList`,
  `CronDelete` every cron, `CronCreate` ONE one-shot resume cron at the window's
  reset plus two minutes, then stop. The directive names the window, its
  percentage, the ceiling and the resume time, and gives the exact cron
  expression in local time with the UTC equivalent beside it.
- A session that never submits a prompt (kept going by Stop continuations or
  one long turn) is paused by its next tool call or its next Stop instead.
- While paused, every other prompt (cron tick, supervisor message, anything) is
  dropped before it reaches the model, every tool except `CronList`,
  `CronDelete`, `CronCreate` and `ToolSearch` (the cron tools are deferred
  built-ins that `ToolSearch` loads) is denied with `continue: false`, and a
  stop is accepted only once exactly the resume cron remains and its pinned
  schedule really fires between now and a day after the reset. The directive
  states the machine's time zone, since the cron is read in local time.
- The owner is never locked out. Every held prompt re-checks the ceiling and
  lifts a pause that no longer applies (no ceiling for the host, or the window
  is back under it or past its reset). `! bin/hooks-daemon usage-pause clear`
  lifts it at once (`usage-pause status` shows it); a `!` command is a shell
  run, not a prompt, so the gate does not see it.
- A pause record is only honoured for 8 days from when it was made, so a stale
  record can never wedge a session for good. An unreadable record is "not
  paused", never an error. A reset within ten minutes is not paused at all.
- Nothing forces the session on or re-arms a cron meanwhile:
  `auto_continue_stop`, both cron stop enforcers, `persistent_cron_assertor`,
  `failsafe_cron_session_advisor` and `recovery_cron_advisor` stand down.
- The resume cron's prompt starts `[tick:usage-resume]`. When it fires, usage
  is re-read. A window past its reset reads as absent, so below the ceiling the
  pause lifts and the model is told to re-create the declared crons and carry
  on; still over it (the weekly window, say) the next resume cron is scheduled.
- The status line shows `⏸ usage HH:MM` while paused.

No ceiling for the host, an unknown hostname, no usage data, or a pause record
that cannot be written never pauses a session; a debug log line says which.
See `usage_pause_gate`, `usage_pause_tool_gate` and `usage_pause_stop_gate`.
