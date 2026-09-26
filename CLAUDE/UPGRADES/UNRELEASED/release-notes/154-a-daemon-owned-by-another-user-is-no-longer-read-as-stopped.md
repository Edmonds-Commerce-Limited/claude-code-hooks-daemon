# Callout: a daemon owned by another user is no longer read as stopped

**Plan**: 00466
**Audience**: operators

The hooks checked whether the daemon was running with `kill -0` on the pid in
its PID file, and read any failure as "stopped". On a process owned by another
user that check fails with a permission error even though the process is
running. The hooks then deleted the PID file and tried to start a second
daemon. Now only "no such process" counts as stopped, and the PID file of a
process that is still alive is never deleted.

A live process is not proof that it is the daemon, though: after a reboot
the pid may belong to some other user's program. The hooks count it as the
daemon only when the daemon's socket answers or the process's command line
shows it is this project's daemon. Otherwise the hook goes on to start the
daemon as usual, and the new daemon replaces the PID file.
