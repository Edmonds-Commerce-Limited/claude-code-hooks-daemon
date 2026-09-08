# Callout: a worktree hook with the daemon down no longer hands Claude Code a JSON blob as the path

**Plan**: 00362
**Audience**: operators

When the hooks daemon could not start, the `WorktreeCreate` forwarder used to
print its JSON error object to stdout and exit 0 — and Claude Code reads that
hook's stdout as the created worktree's absolute path, so the launch was
handed the literal path `/<cwd>/{...json...}`. Every forwarder whose stdout is
read raw (`WorktreeCreate`, `StatusLine`) now writes nothing to stdout on that
branch: the diagnostic goes to stderr and the hook exits non-zero, so worktree
creation fails cleanly instead of naming a garbage directory. The branch is
derived from the event catalogue's `raw_stdout` flag, so a future raw-stdout
event inherits it.
