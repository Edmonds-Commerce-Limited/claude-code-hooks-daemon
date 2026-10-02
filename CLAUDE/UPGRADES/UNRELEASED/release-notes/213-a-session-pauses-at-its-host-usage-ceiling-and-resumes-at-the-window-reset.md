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
  expression in UTC. The Claude Code documentation does not say which time zone
  `CronCreate` reads an expression in, so the directive says that, tells the
  model to use the expression as written, and asks for no clock check (every
  tool but the cron tools is denied while paused). The stop check accepts a
  cron that fires within a day after the resume time, so a zone mismatch delays
  the resume rather than losing it.
- A session that never submits a prompt (kept going by Stop continuations or
  one long turn) is paused by its next main-thread tool call or its next Stop
  instead. The tool call that starts a pause is refused WITHOUT halting the
  turn and carries the full directive, so the model can act on it in the same
  turn. A subagent never starts a pause; its calls in a paused session are
  refused and it is told to stop.
- While paused, every other prompt (cron tick, supervisor message, anything) is
  dropped before it reaches the model, every tool except `CronList`,
  `CronDelete`, `CronCreate` and `ToolSearch` (the cron tools are deferred
  built-ins that `ToolSearch` loads) is denied with `continue: false`, and a
  stop is accepted only once exactly the resume cron remains and its pinned
  schedule really fires between now and a day after the reset. A resume time
  that has come or gone is moved two minutes ahead rather than cleared.
- The owner is never locked out. Every held prompt re-checks the ceiling and
  lifts a pause that no longer applies (no ceiling for the host, or the window
  is back under it or past its reset). `bin/hooks-daemon usage-pause clear`
  removes the pause AND records an override that lasts until the latest reset
  among the windows over the ceiling (at most 8 days): while it is valid no
  pause is started for that session, even though usage is still over the
  ceiling. `usage-pause status` shows the state. Run it in a terminal: whether
  a `!`-prefixed command typed in the session passes through the hooks is
  unverified.
- A pause record is only honoured for 8 days from when it was made, so a stale
  record can never wedge a session for good. An unreadable record is "not
  paused", never an error, and a record that can be written but not read back
  is not a pause either, so a file-permission fault cannot trap a session in a
  deny or stop loop.
- Nothing forces the session on or re-arms a cron meanwhile:
  `auto_continue_stop`, both cron stop enforcers, `persistent_cron_assertor`,
  `failsafe_cron_session_advisor` and `recovery_cron_advisor` stand down.
- The resume cron's prompt starts `[tick:usage-resume]`. When it fires, usage
  is re-read. A window past its reset reads as absent, so below the ceiling the
  pause lifts and the model is told to re-create the declared crons and carry
  on; still over it (the weekly window, say, or a reset only minutes away) the
  next resume cron is scheduled. Usage is only ever reported as back under the
  ceiling when a fresh read showed it.
- The status line shows `⏸ usage HH:MM` while paused.

No ceiling for the host, an unknown hostname, no usage data, or a pause record
that cannot be written and read back never pauses a session; a debug log line
says which. See `usage_pause_gate`, `usage_pause_tool_gate` and
`usage_pause_stop_gate`.
