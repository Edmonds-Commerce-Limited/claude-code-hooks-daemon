# Callout: the nested-install cleanup now actually fires for clients

**Plan**: 00422
**Audience**: operators

`check_for_nested_installation` exempted an outer `.claude/hooks-daemon/`
carrying a `pyproject.toml` from its cleanup of a wrong-root runtime
artifact at `.claude/hooks-daemon/.claude/hooks-daemon/` — but every real
client clone has that file, so the exemption always held and the cleanup
could never run outside the daemon's own repo. It now cleans up
unconditionally. The destructive path is also safer: a nested path that is
itself a symlink is unlinked instead of being handed to `shutil.rmtree`
(which refuses a symlink path outright), and a symlink found while removing
a genuine nested directory has only the link removed, never its target.
