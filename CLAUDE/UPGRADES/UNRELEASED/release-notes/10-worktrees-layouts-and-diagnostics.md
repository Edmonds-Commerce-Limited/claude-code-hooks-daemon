# Callout: four gates that failed on a correctly-configured project

**Plan**: 00419
**Audience**: client projects

Declaring `layout.source_dirs` silently switched off every TDD language
strategy's file-level exclusions, so a project that described its own layout
lost Python's `__init__.py` exemption and was asked for a `test___init__.py`.
The declared layout answers *is this file in a source DIRECTORY?*, which is not
the question the gate needed; file-level exclusions are now consulted ahead of
both location rules, so `layout:` stops subtracting.

The security-downgrade QA check walked into linked worktrees and reported every
file in them a second time, failing the gate with paths that vanish when the
worktree does. Any project with a worktree open when QA ran hit this, and had
no file of its own to fix; `worktrees` is now excluded from the walk.

Worktree seeding gained `optional: true` per entry. An unmarked entry still
fails fast on an absent source, which is the typo-catching behaviour the
feature exists for, but a gitignored file that is legitimately absent — a
secret word list, say — no longer kills every `WorktreeCreate` in the project.
Absence is all `optional` excuses: an entry that escapes the repository is
still fatal.

When a `WorktreeCreate` handler does fail, the forwarder now prints the real
reason on stderr instead of asking whether the handler is enabled — a question
that was misleading precisely when the handler had run and raised.

And `scripts/debug_hooks.sh`, which three documents name as the sanctioned way
to capture real hook payloads before writing a handler, now finds the socket in
both installation layouts and reaches its own `CLAUDE_HOOKS_SOCKET_PATH`
fallback instead of dying silently under `set -e`.
