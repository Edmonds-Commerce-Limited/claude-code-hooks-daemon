# Callout: `stop` falls back to signalling by pid number only when it must

**Plan**: 00466
**Audience**: operators

`hooks-daemon stop` pins the daemon with a pidfd before it proves the pid is
this project's daemon, so no signal can land on a process that reused the
number. It now signals by number only on a platform without pidfd support or
when no file descriptor is free. A daemon that has already exited is reported
as nothing to stop, and any other pidfd failure refuses to signal. When the
proven daemon exits on its own just before `stop` signals it, `stop` no
longer deletes the PID file and socket, which a successor may already own.

After a daemon it stopped has exited, `stop` deletes the PID file only while
it still holds that daemon's pid, and the socket only when nothing is
listening on it. The hooks and the other CLI commands that clear a stale PID
file apply the same pid check, so a daemon started meanwhile keeps its files.
`stop` makes both checks while holding the lock a starting daemon holds, so
it cannot look between a start's removal of the old socket and its bind of
the new one. If a start keeps that lock for 10 seconds, `stop` leaves both
files.
