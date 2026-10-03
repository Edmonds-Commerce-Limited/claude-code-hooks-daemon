# Callout: `stop` leaves a successor's PID file and socket alone

**Plan**: 00466
**Audience**: operators

`hooks-daemon stop` holds on to the exact process it proved is this project's
daemon, so a pid reused while it waits for the daemon to exit never receives
a signal. When the daemon exits on its own before `stop` can signal it, `stop`
reports that and no longer deletes the PID file and socket. A successor may
already own them.

After a daemon it stopped has exited, `stop` deletes the PID file only while
it still holds that daemon's pid, and the socket only when nothing is
listening on it. The hooks and the other CLI commands that clear a stale PID
file apply the same pid check, so a daemon started meanwhile keeps its files.
`stop` makes both checks while holding the lock a starting daemon holds, so
it cannot look between a start's removal of the old socket and its bind of
the new one. If a start keeps that lock for 10 seconds, `stop` leaves both
files.
