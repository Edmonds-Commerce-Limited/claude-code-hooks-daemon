# Callout: the relay and per-event sockets now deny PreToolUse on a transport failure too

**Plan**: 00466
**Audience**: operators

Release notes 41-45 covered the `.claude/init.sh` client. The same fix
landed on the two other places a PreToolUse verdict travels: the Rust relay
binary now fabricates a deny (`deny_pre_tool_use_json`) instead of an empty
`{}` on its own mid-exchange failures — a timeout, an I/O error, or an
oversized/empty response — because `{}` is indistinguishable from a real
judged "allow, nothing to add" to whatever reads it next. The daemon's
per-event `pre-tool-use.sock` does the same on a malformed or oversized
payload, on an uncaught exception, and (this round) on any response that
is not one of PreToolUse's two legitimate verdict shapes, closing the same
gap for a client that dials that socket directly instead of going through
the relay. Every other event's per-event socket contract is unchanged.
