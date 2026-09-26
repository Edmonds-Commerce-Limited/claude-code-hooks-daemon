# Callout: agent files that strict YAML rejects are now read, and `isolation: worktree` in an agent file is honoured

**Plan**: 00468
**Audience**: everyone

Claude Code loads an agent file whose description contains `: ` (for
example `description: finds issues: dead code, ...`), but strict YAML
rejects it. The daemon used to drop such a file, so it could not tell that
the agent had no `Write` tool. It now falls back to reading each top-level
`key: value` line, the way Claude Code does.

`agent_isolation_advisor` no longer advises worktree isolation for an agent
whose own definition declares `isolation: worktree`, because that agent
always runs in its own worktree. This applies to project, user and Claude
Code plugin agents.
