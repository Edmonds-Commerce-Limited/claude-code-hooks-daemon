# Callout: using Claude Code plugins alongside the daemon is now documented

**Plan**: 00468
**Audience**: client projects

A new guide, `docs/guides/CLAUDE_CODE_PLUGINS.md`, covers running Claude Code
plugins in a daemon project. It explains which scope to pick and what project
scope means for collaborators, and it says what the trust dialog does and does
not check. It also explains that plugin hooks run beside the daemon's, where
the daemon never sees them, and that a plugin's `PreToolUse` hook can replace
a tool call's input after the daemon approved the original. Read it before you
enable a plugin that ships `PreToolUse` hooks.

The docs now say "daemon plugin (handler module)" for the `plugins:` block of
`.claude/hooks-daemon.yaml`, so it can't be confused with a Claude Code
plugin. A newly generated `.claude/hooks-daemon.yaml` labels its `plugins:`
block the same way, and in the generated `.claude/HOOKS-DAEMON.md` the
`Plugin` section is now headed `Daemon Plugin`.
