# Callout: the failsafe recovery cron now covers a session from its start

**Plan**: 00394
**Audience**: client projects

A session used to be told to create the failsafe recovery cron only at its
first plan write. A Q&A session, a review, a release run or an `issue-sdlc`
tick that stalled on a rate limit before writing a plan was never resumed. The
new `failsafe_cron_session_advisor` gives the same `CronList`-first advice, with
the same canonical prompt, at the start of every new session. It is silent on a
resumed session, when `recovery_cron_advisor` is disabled (that handler's switch
covers both), and when you declare the failsafe cron under `persistent_crons`,
because `persistent_cron_assertor` states it instead. If you do declare it, the
plan-completion advice no longer tells you to `CronDelete` it, because
`cron_stop_enforcer` would block the stop.
