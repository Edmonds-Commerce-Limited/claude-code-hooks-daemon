# Callout: start waits on a starting daemon, and stop pins the process it proves

**Plan**: 00466
**Audience**: operators

- `hooks-daemon start` and `restart` wait while the daemon is still
  starting. Before, they waited a fixed 5 seconds for its PID file, which
  the daemon writes only after it has loaded its handlers. On a busy host
  they reported "Daemon failed to start (no PID file created)" and exited
  1 while the daemon came up behind them. They now wait while the daemon
  is alive and making progress, up to 30 seconds. They report a failure
  when it exits, when it makes no progress for 10 seconds, or when the 30
  seconds run out. The message says which, and whether a PID file was
  waiting to be proven.
- The proof of which project a daemon serves reads its `--project-root`
  the way the daemon's own argument parser did. When there are two, it
  uses the last one. An abbreviated `--project-r` and the
  `--project-root=PATH` form are also read correctly. Before, the first
  was used. So `bin/hooks-daemon --project-root B start`, run from project
  A's wrapper, started B's daemon but was attributed to A. A's
  single-daemon enforcement could then stop it, and B could not. A
  command line that the parser would reject, or that names a relative
  root, now proves nothing.
- `stop`, `restart` and single-daemon enforcement open a pidfd for the
  process before they check its identity, and send every signal through
  it. A process id reused at any point after that can only make the
  signal fail. Where the kernel has no pidfds, the checked psutil handle
  still sends the signal, as before.
- Stale runtime files are removed only under the start lock, and only
  while they are dead. This covers the installer's pre-install check and
  cleanup, and single-daemon enforcement outside a container. A live
  socket, or a PID file naming a live process (another user's
  included), is left in place.
