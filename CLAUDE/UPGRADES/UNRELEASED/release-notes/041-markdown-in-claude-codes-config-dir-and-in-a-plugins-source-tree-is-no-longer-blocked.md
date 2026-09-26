# Callout: markdown in Claude Code's config dir and in a plugin's source tree is no longer blocked

**Plan**: 00468
**Audience**: everyone

Findings P4 and G8. This affects everyone whose Claude config dir sits inside
the project, and anyone who develops a Claude Code plugin in their repository.

`markdown_organization` judged two kinds of Claude Code file by the
project's documentation layout, and denied them with
`R-MARKDOWN-WRONG-LOCATION`:

- **Files in Claude Code's config dir** (`$CLAUDE_CONFIG_DIR`, else
  `~/.claude`) when that dir is symlinked into the project, as ccy does. A
  write to a plugin's data dir, a user agent, command, rule, output style or
  skill resolved into the project, and was then denied. Markdown there is now
  never judged by the layout rules. The untracked auto-memory policy
  (`allow_untracked_claude_memory`) still applies as before.
- **A plugin's own components.** In a directory that holds
  `.claude-plugin/plugin.json` or `.claude-plugin/marketplace.json`, markdown
  under `agents/`, `commands/`, `skills/` and `output-styles/` is where Claude
  Code loads it from, and is now allowed. Other markdown in a plugin tree is
  judged as before.

The deny message's list of allowed locations now names `.claude/skills/`,
plugin roots and the config dir.
