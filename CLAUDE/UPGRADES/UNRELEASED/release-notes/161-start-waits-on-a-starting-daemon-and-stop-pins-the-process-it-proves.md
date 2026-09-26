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
  seconds run out. The message says which, and what the PID file held: no
  file, a pid that is no longer running, or a pid still waiting to be
  proven. A daemon waiting for another start to finish with the start
  lock says so, and is not given up on as stuck.
- A hook that has to start the daemon no longer waits for `start` to
  finish. It waits at most 15 seconds from its own start. If the daemon is
  still starting then, a PreToolUse call is denied with "the daemon is
  starting; retry" instead of the hook running into Claude Code's 60-second
  timeout, which lets the call through unchecked. Retry the call; nothing
  needs fixing.
- Only one start of a daemon runs at a time. A `start` that finds another
  still under way waits for it, up to 30 seconds, and then uses the daemon
  it started. It launches its own only if that start failed. Before, a
  retried hook found no PID file yet and started a second daemon. In a
  container, that start's single-daemon enforcement stopped the daemon
  still starting, so a start slower than the hook's 15 seconds never
  finished. A start that never finishes blocks later ones and says so.
  `stop` (and `restart`) ends it, after proving its pid the way it proves
  a running daemon's. The lock is `<socket>.launch.lock`, beside the
  socket.
- The proof of which project a daemon serves reads its `--project-root`
  the way the daemon's own argument parser did. When there are two, it
  uses the last one. An abbreviated `--project-r` and the
  `--project-root=PATH` form are also read correctly. Before, the first
  was used. So `bin/hooks-daemon --project-root B start`, run from project
  A's wrapper, started B's daemon but was attributed to A. A's
  single-daemon enforcement could then stop it, and B could not. A
  command line that the parser would reject, or that names a relative
  root or a root containing `..`, now proves nothing. A `..` after a
  symlink goes somewhere other than where it seems to. For example,
  `/var/run/../workspace` is `/workspace` when `/var/run` links to `/run`.
  Roots are compared the way the daemon serves them, with symlinks
  resolved.
- `stop`, `restart` and single-daemon enforcement open a pidfd for the
  process before they check its identity, and send every signal through
  it. A process id reused at any point after that can only make the
  signal fail. Where the kernel has no pidfds, the checked psutil handle
  still sends the signal, as before. Any other failure to open the pidfd
  now stops the signal and gives a warning, instead of crashing `start` or
  the installer.
- Stale runtime files are removed only under the start lock, and only
  while they are dead. This covers the installer's pre-install check and
  cleanup, and single-daemon enforcement outside a container. A live
  socket, or a PID file naming a live process (another user's
  included), is left in place. The installer takes the start lock that
  sits next to the daemon's real socket. That is true even when a long
  project path moves the socket to the short fallback directory.
