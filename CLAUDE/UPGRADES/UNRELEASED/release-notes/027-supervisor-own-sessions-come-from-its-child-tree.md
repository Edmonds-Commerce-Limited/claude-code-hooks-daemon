# Callout: the ccy supervisor is safe outside a private PID namespace

**Plan**: 00551
**Audience**: operators

The ccy supervisor now counts a session as its own only when the session id is in the environment of the Claude process it started, or of one of that process's descendants. Before this, it took every session id it could see in `/proc`, which is safe only inside a private container PID namespace. On a host, or with a shared PID namespace, it could act on another terminal's compaction signals and sidecars (reported as issue #138). The change reaches a running session by the worker hot reload; until the next ccy relaunch, the reloaded worker finds the Claude process as the older host's single other child, and acts on nothing if that is ambiguous.
