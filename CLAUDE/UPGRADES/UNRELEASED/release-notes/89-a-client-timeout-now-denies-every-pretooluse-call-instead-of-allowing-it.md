# Callout: a client timeout now denies every PreToolUse call instead of allowing it

**Plan**: 00466
**Audience**: operators

`.claude/init.sh` now fails CLOSED on its own socket timeout, a crashed
daemon, or a malformed response, but only for `PreToolUse`: previously any
of these emitted an advisory-only `hookSpecificOutput`, which Claude Code
reads as an ALLOW. If a host is slow enough that the daemon's own
`daemon.chain.deadline_seconds` is not the thing firing first, every tool
call is now denied with a `socket_timeout`/`malformed_response` reason until
the host recovers — this trades a slow-host false-deny for closing a
real fail-open, and is the single most operator-visible behaviour change in
Plan 00466. See release note 41 for the full context.
