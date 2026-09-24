# Claude Code plugins alongside the daemon

You can use Claude Code plugins in a project that runs the hooks daemon. They
work side by side, but a few things are worth knowing before you enable one.

Full detail, with citations to the Claude Code documentation, lives in
[CLAUDE/ClaudeCodePlugins.md](../../CLAUDE/ClaudeCodePlugins.md).

## "Plugin" means two things

- A **Claude Code plugin** is a package Claude Code installs from a
  marketplace, bundling skills, agents, hooks or servers.
- A **daemon plugin (handler module)** is a custom handler the daemon loads
  from the `plugins:` block of `.claude/hooks-daemon.yaml`. See
  [CONFIGURATION.md](CONFIGURATION.md#daemon-plugins-handler-modules).

This page is about Claude Code plugins.

## Pick the scope deliberately

- **User** scope: just you, in every project.
- **Local** scope: just you, in this project. Best for trying a plugin out.
- **Project** scope: written to the committed `.claude/settings.json`, so it
  reaches every collaborator. Review it like any other shared settings change.

## The trust gate is not a review

Claude Code loads project-scoped plugin content only after you trust the
folder, but trusting it does not check what the plugin does. Plugins run code
with your user privileges.

## Plugin hooks run beside the daemon's

A plugin's hooks run in parallel with the daemon's, and the daemon never sees
them. A daemon deny always wins. But a plugin's `PreToolUse` hook can
**replace a tool call's input** after the daemon has approved the original, so
the tool runs with input the daemon never judged. Only enable plugins with
`PreToolUse` hooks that you trust at that level.

## Plugin agents and skills have scoped names

Plugin skills are called as `/<plugin-name>:<skill>`, and plugin agents as
`<plugin-name>:<agent>`. Use the scoped name anywhere you refer to one.
