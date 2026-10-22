# Callout: session modes are visible on the status line and logged

**Plan**: 00501
**Audience**: operators

A session's modes are now visible and explained:

- **Status line.** The new `session_mode_indicator` segment (on by default, priority 18) shows `⚑ <top mode> +N`: the top mode by precedence (usage-paused > goal-blocked > awaiting-human > focus > unattended) and how many more are active, with the focus task when focus leads. It shows nothing when the session has no mode. The daemon-wide `unattended` mode is shown there too. A red `⚑ modes unreadable` or `⚑ usage-pause record unreadable` means the mode state could not be read; see the daemon log. `hooks-daemon status-line-explained` describes it.
- **After a daemon restart**, the next prompt in each session gets one `SESSION MODE:` line, whatever the prompt is. The line names the modes that survived the restart and the modes the restart cleared. It also says when the daemon is in unattended mode. Expiries are stated in the same single line. A usage-paused session sees no prompt until its resume cron fires, so a usage pause recorded before the restart is stated on the resume tick that finds usage still over the ceiling, next to the instruction to stay paused.
- **A focus change or renewal that cannot be recorded** is stated to the agent (`FOCUS MODE NOT CHANGED` or `FOCUS MODE NOT RENEWED`, with the error) as well as logged, and the pending `SESSION MODE:` line is still delivered on the same prompt.
- **Transition log.** Every mode entered, exited, expired or cleared by a restart is recorded with what triggered it in `session-mode-transitions.jsonl` under the daemon's untracked directory. The log keeps the newest 500 records. `hooks-daemon mode-history [--session ID] [--limit N] [--json]` prints every session's live modes and the recent transitions; an unreadable log is reported as an error, never as an empty history. A log whose content does not parse is moved aside under a unique `session-mode-transitions.jsonl.<time>.<token>.corrupt` name and a fresh log is started. A log that cannot be read (for example, permission denied) is left where it is, and the failure is logged.
