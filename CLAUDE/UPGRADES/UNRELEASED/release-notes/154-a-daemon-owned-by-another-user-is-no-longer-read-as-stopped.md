# Callout: a daemon owned by another user is no longer read as stopped

**Plan**: 00466
**Audience**: operators

The hooks checked whether the daemon was running with `kill -0` on the pid in
its PID file, and read any failure as "stopped". On a process owned by another
user that check fails with a permission error even though the process is
running. The hooks then deleted the PID file and tried to start a second
daemon. Now only "no such process" counts as stopped: a daemon the hook may
not signal is treated as running, and its PID file stays.
