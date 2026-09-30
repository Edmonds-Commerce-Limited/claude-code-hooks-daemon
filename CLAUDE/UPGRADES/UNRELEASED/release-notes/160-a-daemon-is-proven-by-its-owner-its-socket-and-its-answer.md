# Callout: a daemon is proven by its owner, its socket and its answer

**Plan**: 00466
**Audience**: operators

- A command line proves a process is this project's daemon only when the
  process belongs to you: both its real and effective user ids must be
  yours. Root may signal any process, so a hook or `stop` running as root
  used to accept another user's process that named your project in its
  arguments. `stop`, `restart`, the hooks and `hooks-daemon start` now
  refuse such a process.
- The daemon answers a new `identity` request with the project it serves
  and its pid. Where the hooks and `hooks-daemon start` use the socket as
  proof that a PID file's process is your daemon, the answer must name
  your project, and for `start` also that pid. Before, any process
  listening on the socket counted. Deciding whether a live socket may be
  reused or removed still needs only a connection, so a live daemon's
  socket is never taken over.
- A daemon started without `--project-root` is matched to the project whose
  socket it listens on, or the project it recorded at startup. The venv it
  runs from no longer counts, because worktrees can share a venv.
- The hooks read a process's command line split at its NUL bytes, the way
  the daemon reads it, so an argument containing newlines can no longer
  pass as a daemon launch. The launch must be exactly
  `-m <cli> --project-root <root> start|restart` with no second root.
- When the hook cannot tell whether the daemon is running, PreToolUse
  denies the call. The CI passthrough applies only when the daemon is
  really down.
