# Callout: a turn that ends on an API error is recorded and shown on the status line

**Plan**: 00470
**Audience**: operators

A turn that ends on a rate limit or a credential error ends in a `StopFailure` hook, and Claude Code ignores that hook's output, so a persistent session that hit its limit, or whose credential lapsed, used to stop and say nothing. Two new default-on handlers now write it down. `stop_failure_recorder` records a turn that ended on `rate_limit`, `authentication_failed` or `cloud_credential_error` (the error type only, never the API's own text), and the `usage_indicator` status-line segment shows the latest unresolved one as a chip. `stop_failure_resolver` clears that session's record when it submits its next prompt (a human, a cron tick or a resume), so the chip goes away once the session moves on; if that prompt fails too, a newer failure is recorded. Both are silent and fail open. A project config that lists its `stop_failure` and `user_prompt_submit` handlers explicitly should add them; no other action is needed.
