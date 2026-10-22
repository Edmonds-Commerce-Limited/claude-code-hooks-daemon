# Callout: session modes are visible on the status line and logged

**Plan**: 00501
**Audience**: operators

A session's modes are now visible and explained:

- **Status line.** The new `session_mode_indicator` segment (on by default, priority 18) shows `⚑ <top mode> +N`: the top mode by precedence (usage-paused > goal-blocked > awaiting-human > focus > unattended) and how many more are active, with the focus task when focus leads. It shows nothing when the session has no mode. The daemon-wide `unattended` mode is shown there too. A red `⚑ modes unreadable` or `⚑ usage-pause record unreadable` means the mode state could not be read; see the daemon log. `hooks-daemon status-line-explained` describes it.
- **After a daemon restart**, the next prompt in each session gets one `SESSION MODE:` line, whatever the prompt is. The line names the modes that survived the restart, including a usage pause recorded before it, and the modes the restart cleared. It also says when the daemon is in unattended mode. Expiries are stated in the same single line.
- **Transition log.** Every mode entered, exited, expired or cleared by a restart is recorded with what triggered it in `session-mode-transitions.jsonl` under the daemon's untracked directory. The log keeps the newest 500 records. `hooks-daemon mode-history [--session ID] [--limit N] [--json]` prints every session's live modes and the recent transitions; an unreadable log is reported as an error, never as an empty history.
