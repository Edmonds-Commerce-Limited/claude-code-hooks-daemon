# Callout: `daemon_restart_verifier` becomes a project handler

**Plan**: 00370
**Audience**: client projects

`daemon_restart_verifier` only ever fired inside the hooks daemon repository
itself: its `matches` refused every other project, because a client cannot
break the daemon by committing. Plan 00330 gave it a relevance declaration so
`/hooks-daemon optimise` stopped scoring a client project against a handler
that could not do anything for it — but the handler still never belonged in
the shared, cross-project library. Pure self-dogfooding is exactly what the
project-handler surface (`.claude/project-handlers/`) exists for.

The built-in handler is removed entirely — source, tests, config key,
generated docs. Its one-line advisory ("verify the daemon restarts before
committing") now lives as a project-level handler in the hooks daemon
repository's own `.claude/project-handlers/pre_tool_use/`, the same
behaviour with no relevance-scoring bandage needed, and this repository's
own reference example of a project handler for anyone standing up their
first one.

Nothing to change in a client config: `daemon_restart_verifier` is
registered as a retired handler name, so a leftover
`daemon_restart_verifier: enabled: true` (or `false`) validates cleanly and
is simply ignored — it never mattered outside the hooks daemon repository's
own checkout, and can be deleted at your convenience.
