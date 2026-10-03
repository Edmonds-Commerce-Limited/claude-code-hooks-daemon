# Callout: the hook denies in time, and proves which process is the daemon

**Plan**: 00466
**Audience**: operators

- When the daemon cannot start, PreToolUse now denies within the same
  budget as before (about 15 seconds of waiting), measured by the clock. The
  wait used to count checks, and with a PID file the hook could not clear,
  each check could take half a second, so the hook could run past its 60
  second timeout and let the call through unjudged.
- A PID file naming a live process no longer counts as a running daemon by
  itself. The process must be this project's daemon: its command line shows
  it, or the daemon's socket answers. After a reboot a stale PID file can
  name any process, and the hooks used to skip starting the daemon. For a
  process of another user's, only the socket answering counts.
- `hooks-daemon start` now reports the PID of the daemon it actually
  started. With a stale PID file present it could report the old PID as
  "started successfully".
- A daemon root in `HOOKS_DAEMON_ROOT_DIR` that is not an install of this
  project is no longer used to judge the PID file.
- The start lock (`<socket>.start.lock`) can be taken only by the user who
  created it (or root). A second user sharing the same directory now gets
  an error naming both users, and nothing is removed.
- A recovery command is exempt only when its launcher really is a
  `bin/hooks-daemon`.
