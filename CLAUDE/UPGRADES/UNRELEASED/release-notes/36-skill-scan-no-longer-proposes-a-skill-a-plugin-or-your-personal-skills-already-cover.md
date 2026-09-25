# Callout: skill-scan no longer proposes a skill that a plugin or your personal skills already cover

**Plan**: 00468
**Audience**: everyone

`hooks-daemon skill-scan` tells the judging model which skills already
exist, so that it does not propose one twice. That list used to hold only
the project's `.claude/skills/` and `.claude/commands/`. It now also holds
your personal skills and commands under the Claude config dir, and every
enabled Claude Code plugin's skills by the name you invoke them with, such
as `defence-before-fix:dbf`. The report's "existing skills" line counts
them too. skill-scan and `tool-report` now read transcripts from
`$CLAUDE_CONFIG_DIR/projects` when that variable is set, instead of always
`~/.claude/projects`.
