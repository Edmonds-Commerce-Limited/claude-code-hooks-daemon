# Callout: Claude Code plugin agents are now recognised by the read-only dispatch logic

**Plan**: 00468
**Audience**: everyone

An agent that comes from an enabled Claude Code plugin, such as
`defence-before-fix:conformance-reviewer`, used to be unknown to the daemon.
So a plugin agent with no `Write` tool got no `dispatch_declaration`
advisory when its brief named a report file. When its reply was too long,
`subagent_report_size_blocker` told it to "write the full report to a file",
and it did not get the warning against a Bash heredoc. A heredoc was then
the agent's only way to write a file, and it bypasses the content guards.
The daemon now reads your installed and enabled plugins, finds the agent by
its scoped id (`<plugin>[:<subfolder>...]:<name>`) and treats it like any
other read-only agent.

The path the size blocker tells an agent to write to now uses `_` in place
of the `:` in a plugin agent's name. That matches the name the daemon uses
for the reply it saves itself. User agents and plugins are looked up under
`$CLAUDE_CONFIG_DIR` when it is set, not always under `~/.claude`.
