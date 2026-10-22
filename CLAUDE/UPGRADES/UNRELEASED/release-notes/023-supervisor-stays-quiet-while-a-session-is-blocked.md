# Callout: the ccy supervisor types no work-driving prompt while a session is blocked

**Plan**: 00501
**Audience**: operators

The ccy supervisor now reads the daemon's per-session `<session>.session-modes` file. While its session is blocked (`awaiting-human` or `goal-blocked`) it does not type the post-compact `continue`, a `/goal`, the standing-authorisation reminder or the session-actions directive; each skip is a named `noop:` line in `decision.log` (for example `noop: post-compact continue skipped: session BLOCKED (awaiting-human)`). `/compact` itself still runs. A pending goal clear now wins over a pending goal while blocked, and the five-per-process goal-clear cap does not refuse it. A session-modes file the supervisor cannot read is not treated as "no modes": the same prompts are withheld, `decision.log` names the file and the error, and the status line shows a warning until the file is readable again. The change is in the supervisor's worker, so it reaches a running session by the worker hot reload; no ccy relaunch is needed.
