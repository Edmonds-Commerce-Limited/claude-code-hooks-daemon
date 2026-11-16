# Callout: the generated hook wrappers name no machine-specific path

**Plan**: 00609
**Audience**: client projects

The relay hot-path block the daemon generates into each `.claude/hooks/*` wrapper embedded the absolute checkout path (the `BASH_SOURCE` prefix test, the untracked directory, the relay binary default and the daemon root passed to the relay). On a deeply nested checkout it also embedded the short fallback events directory, a path made of a runtime directory, a uid and two hashes. A project that tracks its wrappers therefore got a dirty checkout whenever another machine or root regenerated them. The nc rung's trailing events-directory argument carried the same fallback path.

The wrappers are now byte-identical in every root on every machine. The checkout root is derived at run time from `${BASH_SOURCE[0]}` (which must be an absolute path ending in `/.claude/hooks/<name>`; anything else takes the legacy transport as before), and only the layout below the root (`untracked` or `.claude/hooks-daemon/untracked`) is written. No extra process is spawned on the hot path.

When the natural events directory overflows the AF_UNIX path limit, the daemon binds in its short fallback root and now publishes where, in `untracked/events<host-suffix>.location` (two lines: the untracked dir it was written for, then the events dir). The wrapper and `init.sh`'s nc rung read it back with the `read` builtin and trust it only when it names their own untracked dir. `HOOKS_DAEMON_EVENTS_DIR` still wins over everything.

Behaviour change: a copy of a wrapper (a git worktree inherits the tracked file) now dials its own checkout's socket instead of skipping the hot path, and finds none unless that checkout runs a daemon.

Upgrade: the next converge or upgrade rewrites each wrapper that still carries the old embedded block once; a second regeneration is a no-op. A project that tracks its wrappers should expect exactly one diff to commit. A daemon running an older release does not publish the location file, so on an overflowing layout the wrapper falls through to the legacy transport until the daemon is restarted.
