# Callout: `hooks-daemon status` shows the relay repair state beside its relay WARNING

**Plan**: 00608
**Audience**: operators

When `hooks-daemon status` warns that the configured relay binary is missing or cannot run, it now also prints what the background repair of that cause recorded: `Relay repair: <status> - <detail>` and `Relay repair log: <path>`, or `Relay repair: no attempt recorded for this cause` naming the state file that is absent. That tells a repair that failed apart from one that was never attempted. The lines are read from the repair's own state file in the daemon's untracked directory, in both the running and not-running outputs, and the exit code is unchanged (liveness only). Nothing is printed when the relay is disabled or its binary is usable.
