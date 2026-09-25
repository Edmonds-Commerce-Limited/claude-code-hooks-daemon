# Callout: CLAUDE_CONFIG_DIR is honoured for your settings and transcripts

**Plan**: 00468
**Audience**: everyone

This affects everyone who sets `CLAUDE_CONFIG_DIR`.

When `CLAUDE_CONFIG_DIR` is set, Claude Code keeps its user settings and
session transcripts there instead of `~/.claude`. Several daemon features
read `~/.claude` unconditionally, so they looked at the wrong files:

- the status line's effort level, the prompt-cache TTLs `cache-gaps` reports, the
  `optimal_config_checker` session-start audit and `cli check` read
  `settings.json` from the wrong place;
- `hooks-daemon cache-gaps` with no `--transcript` looked for the project's
  newest transcript in the wrong place, and reported none, or an older one;
- `skill-scan` and `tool-report` looked for transcripts in the wrong place.

All of them now use `$CLAUDE_CONFIG_DIR` when it is set, and `~/.claude`
otherwise. The daemon reads the variable from its own environment, which is
fixed when it starts. If you change `CLAUDE_CONFIG_DIR`, restart the daemon.
