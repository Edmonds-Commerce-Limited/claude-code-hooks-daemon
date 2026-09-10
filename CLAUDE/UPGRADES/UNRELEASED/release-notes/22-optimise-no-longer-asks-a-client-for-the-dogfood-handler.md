# Callout: `optimise` no longer scores a client for the dogfooding-only handler

**Plan**: 00330
**Audience**: client projects

`daemon_restart_verifier` only ever fires inside the hooks daemon repository
itself: its `matches` refuses every other project, because a client cannot
break the daemon by committing. It never said so to the config-optimisation
review, though, so `/hooks-daemon optimise` scored a client project's Safety
area `WARN (21/22)` with the one shortfall being a handler that would have
been inert if enabled.

The handler now declares its relevance: inside the daemon repository it is
recommended as before; anywhere else the report lists it as "not applicable
here" with the reason, and the Safety area scores against the handlers that
can actually do something for that project. Nothing to change in a client
config; a `daemon_restart_verifier: enabled: true` that was added to satisfy
the old score is harmless and can be removed.
