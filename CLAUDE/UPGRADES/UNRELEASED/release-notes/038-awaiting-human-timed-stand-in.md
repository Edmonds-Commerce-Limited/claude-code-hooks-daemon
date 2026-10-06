# Callout: an `[awaiting-human]` stop now schedules a timed stand-in

**Plan**: 00470
**Audience**: operators

One open question used to halt a session until the owner came back. A main-thread stop that declares `[awaiting-human]` is now blocked until the session also holds a one-off cron about three hours out. The block message gives the exact `CronCreate` (`recurring: false`, a schedule, and the prompt to paste).

- If the awaiting-human marker is still live when it fires, the session dispatches a `model: fable` sub-agent that reads the pending question and the options laid out in the last stop message, chooses one, and the session carries on. If a real owner message has arrived, the tick is a no-op.
- The choice is journalled with `mkplan.bash --journal` as the stand-in's ruling, never as the owner's, and a later owner message can overturn it. Only engineering options may be chosen. Releases, force deletes, remote branch deletes, QA suppressions, history rewrites, upgrade approvals and anything a guard says to ask the user for stay blocked, and the stand-in records that it declined.
- The cron is recognised by a `[tick:stand-in]` first line, so a live marker does not drop its tick. Sub-agent and teammate stops are never asked for one. Like the declared-cron enforcers, it applies only where `persistent_crons.enabled` is true and the stop payload carries `session_crons`; an absent field never blocks.
- The delay is `handlers.stop.auto_continue_stop.options.stand_in_delay_hours` (default 3; above 0 and below 24, checked at config load).
- The block is made by `auto_continue_stop`, not `cron_stop_enforcer`: the enforcer runs before the marker is written and cannot see the declaration.
