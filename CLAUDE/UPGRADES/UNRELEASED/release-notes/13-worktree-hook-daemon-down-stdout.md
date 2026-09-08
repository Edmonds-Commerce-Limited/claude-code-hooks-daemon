# Callout: a worktree hook with the daemon down no longer hands Claude Code a JSON blob as the path

**Plan**: 00362
**Audience**: operators

When the hooks daemon could not start, the `WorktreeCreate` forwarder used to
print its JSON error object to stdout and exit 0 — and Claude Code reads that
hook's stdout as the created worktree's absolute path, so the launch was
handed the literal path `/<cwd>/{...json...}`. A forwarder whose stdout is
read raw never puts JSON there now: `WorktreeCreate` prints nothing (the
stdout is a parsed value), the status line keeps its visible `⚠️ DAEMON FAILED`
marker (the stdout is a display line), and both send the diagnostic to stderr
and exit non-zero, so worktree creation fails cleanly instead of naming a
garbage directory. The branch is derived from the event catalogue
(`raw_stdout` plus a per-event `daemon_down_stdout` text), so a future
raw-stdout event inherits it.
