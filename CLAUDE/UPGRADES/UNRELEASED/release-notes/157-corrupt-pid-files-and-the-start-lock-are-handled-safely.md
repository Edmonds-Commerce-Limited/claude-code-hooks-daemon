# Callout: corrupt PID files and the start lock are handled safely

**Plan**: 00466
**Audience**: operators

- A PID file holding `0`, a negative number, `1`, anything that is not a
  number, or nothing at all is now treated as corrupt. It never counts as a
  running daemon. `kill -0 0` used to succeed, because `0` means "my own
  process group", so such a file kept the hooks from ever starting the
  daemon.
- The hooks remove a stale or corrupt PID file only while holding the lock
  a starting daemon holds when it writes its own PID file, and only if the
  file still holds what was read. A daemon starting at that moment keeps
  its file. The daemon's own CLI commands no longer remove a stale PID file
  as a side effect of reading it; a starting daemon overwrites it.
- The start lock (`<socket>.start.lock`) is no longer opened through a
  symlink, and must be a regular file. If it cannot be opened, `stop`
  leaves the PID file and socket where they are rather than removing them
  without the lock.
