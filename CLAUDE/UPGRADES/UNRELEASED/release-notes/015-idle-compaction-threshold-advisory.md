# Callout: Optimal-config check encourages the lowest idle compaction threshold

**Audience**: client projects

`hooks-daemon check` gains an "Idle Compaction Threshold" entry. When idle compaction is in effect and `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` is unset (Claude Code defaults to 200000) or set above 100000, it warns and prints the fix: add `"env": {"CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS": "100000"}` to `~/.claude/settings.json`. 100000 is the lowest value Claude Code accepts; lower values are raised to it. The variable is read from the shell, the project settings files and the user settings. The check is advisory only: the daemon never writes or overwrites this value. No configuration changes.
