# Callout: a deep file path no longer stalls PreToolUse

**Plan**: 00466
**Audience**: operators

On Python 3.12 and later, the stdlib's `PurePath.relative_to` and
`is_relative_to` cost time quadratic in a path's depth. Several PreToolUse
handlers use them on a tool call's `file_path`, which the caller chooses, so a
very deep path made them slow. The daemon now tests containment with a linear
helper everywhere, and a semgrep rule keeps the stdlib forms out of the code.

`markdown_organization` had a worse case of its own. It checked every ancestor
of a `.md` path for a Claude Code plugin manifest and logged each failed check
with the full path, so a 16 KB path took about 15 seconds and wrote megabytes
of log. It now checks only directories that exist. Normal paths get the same
answers as before.
