# Callout: Claude Code plugins that ship hooks are named at session start and in `health`

**Plan**: 00468
**Audience**: everyone

Findings G1 and G2. This affects everyone who enables Claude Code plugins.

A Claude Code plugin can ship its own hooks. They run beside the daemon's,
and the daemon never sees them, so none of its guards or its hook
registration policy applies to them. A daemon deny still wins over any plugin
hook. But a plugin `PreToolUse` hook can return `updatedInput`, which replaces
the input of a call the daemon allowed. The tool then runs with input the
daemon never judged.

**New advisory, `plugin_hooks_advisor`** (on by default, never blocks). At
the start of each new session it names every enabled plugin that ships hooks,
lists their events, and singles out `PreToolUse`. Once you have reviewed a
plugin and trust it, add its id to the acknowledged list to silence the
advisory for it:

```yaml
handlers:
  session_start:
    plugin_hooks_advisor:
      options:
        acknowledged_plugins: [my-plugin@my-marketplace]
```

**`hooks-daemon health`** gains a "Claude Code plugin hooks" section. It lists
every plugin with hooks, marks the acknowledged ones, and names any enabled
plugin the daemon could not resolve, whose hooks are therefore unknown. It
never changes the exit code.

The full explanation is in `CLAUDE/ClaudeCodePlugins.md`, under "Plugin hooks
run in parallel with the daemon's".
