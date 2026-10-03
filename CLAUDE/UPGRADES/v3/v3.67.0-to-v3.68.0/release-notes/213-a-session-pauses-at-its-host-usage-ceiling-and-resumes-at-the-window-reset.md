# Callout: a session pauses at its host usage ceiling and resumes at the window reset

**Plan**: 00479
**Audience**: operators

A host whose `hosts:` entry sets a `usage_ceiling` now pauses a session when a
usage window reaches it, instead of letting the session run into the account's
hard limit. The pause does not end the session:

- The prompt that trips the ceiling carries a directive: `CronList`,
  `CronDelete` every cron, `CronCreate` ONE recurring resume cron on the
  schedule `*/10 * * * *`, then stop. The directive names the window, its
  percentage, the ceiling and the resume time (in UTC). The cron names no clock
  time, so no host time zone can misplace it: it fires every ten minutes, a
  tick before the resume time is dropped at zero cost, and the first tick at or
  after it re-reads usage and lifts the pause. The directive also tells the
  model to wind up its subagents: start no new ones, let running ones finish
  (it may message them to wrap up), and `TaskStop` idle or finished ones.
- A session that never submits a prompt (kept going by Stop continuations or
  one long turn) is paused by its next tool call or its next Stop instead. A
  subagent over the ceiling starts the pause too, so subagent activity cannot
  keep the session from pausing. The main thread's first call after that is
  refused WITHOUT halting the turn and carries the full directive, so the model
  can act on it in the same turn. A subagent's own calls are never denied: in-
  flight subagents finish, and a little extra usage from them is accepted.
- While paused, every other prompt (cron tick, supervisor message, anything) is
  dropped before it reaches the model, every main-thread tool except
  `CronList`, `CronDelete`, `CronCreate`, `ToolSearch` (the cron tools are
  deferred built-ins that `ToolSearch` loads), `SendMessage` and `TaskStop` is
  denied with `continue: false` (which includes starting a new subagent), and a
  stop is accepted only once exactly the resume cron remains on its schedule.
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
  pause lifts and the model is told to `CronDelete` the resume cron, re-create
  the declared crons and carry on; still over it (the weekly window, say, or a
  reset only minutes away) the pause is renewed and the same resume cron stays
  in place. Usage is only ever reported as back under the ceiling when a fresh
  read showed it.
- The status line shows `⏸ usage HH:MM` while paused.

No ceiling for the host, an unknown hostname, no usage data, or a pause record
that cannot be written and read back never pauses a session; a debug log line
says which. See `usage_pause_gate`, `usage_pause_tool_gate` and
`usage_pause_stop_gate`.
