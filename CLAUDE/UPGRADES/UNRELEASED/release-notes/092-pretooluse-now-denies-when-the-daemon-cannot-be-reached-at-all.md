# Callout: PreToolUse now denies when the daemon cannot be reached at all

**Plan**: 00466
**Audience**: operators

Release note 43 closed the "daemon reached but silent" fail-open. This
closes the other half: for an installed project, `.claude/init.sh` now
denies `PreToolUse` when the socket is missing, the connection is refused,
or the daemon fails to start — cases that previously fell through to the
same advisory-only `hookSpecificOutput` Claude Code reads as an ALLOW. The
one exception is the exact command that recovers the daemon (`bin/hooks-daemon`
or `.claude/hooks-daemon/bin/hooks-daemon`, with `restart`/`status`/`start`/
`logs`/`stop`), which is never denied by this change. A daemon's accept
backlog filling up (a wedged daemon that has stopped calling `accept()`) is
now also denied rather than allowed, and the per-event `pre-tool-use.sock`
itself refuses to emit anything that is not a judged verdict shape, closing
the same gap on the relay rung. A project that is genuinely not installed at
all is unaffected and still fails open, so a fresh clone before first
install still works normally.
