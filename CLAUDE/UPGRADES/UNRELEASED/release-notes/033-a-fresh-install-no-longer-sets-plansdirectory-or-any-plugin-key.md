# Callout: a fresh install no longer sets plansDirectory, and never ships a plugin key

**Plan**: 00468
**Audience**: client projects

The `settings.json` the installers ship is also the daemon repository's own,
so a setting added there for the daemon's own development reached every
client. `plansDirectory: ./CLAUDE/Plan` shipped that way: a fresh shell
install sent Claude Code's plan mode into a `CLAUDE/Plan/` directory even in
projects that never enabled the plan workflow. It no longer ships, and a test
now fails if `plansDirectory`, `enabledPlugins` or `extraKnownMarketplaces`
reaches a client by any install or upgrade route. That means no Claude Code
plugin is ever enabled in your project by the daemon.

An existing `plansDirectory` in your `settings.json` is yours and is kept on
upgrade. If you enable the plan workflow on a new install, set it yourself;
`CLAUDE/LLM-INSTALL.md` now has the step. `markdown_organization`'s
`enforce_claude_code_sync` check also reads `.claude/settings.local.json`, as
Claude Code does, so a value kept there is honoured.
