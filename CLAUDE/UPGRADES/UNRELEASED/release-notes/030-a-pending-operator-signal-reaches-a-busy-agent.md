# Callout: a host reboot or shutdown warning now reaches an agent in the middle of a long turn, through the new default-enabled `operator_signal_notice` handler

**Plan**: 00508
**Audience**: operators

`hooks-daemon signal` writes a per-session warning that the host will reboot or shut down, or that a warned reboot is cancelled. The ccy supervisor types it into the session only when the session is idle with an empty input box, so an agent in a long turn was told after the stated minutes could already have run out. The new PostToolUse handler `operator_signal_notice` (priority 38, enabled by default) adds the same rendered warning as hook context at the next tool call, once per signal. It reads one known file per event, ignores a malformed, expired, unknown-kind or other-session file with a logged reason, and never deletes or rewrites the file, so the supervisor's idle-time injection is unchanged and the agent may see the same warning a second time when it goes idle. Opt out with `handlers.post_tool_use.operator_signal_notice.enabled: false` (reported as issue #77).
