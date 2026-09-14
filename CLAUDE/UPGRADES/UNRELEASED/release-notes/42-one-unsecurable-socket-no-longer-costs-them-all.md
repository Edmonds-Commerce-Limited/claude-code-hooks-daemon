# Callout: one unsecurable socket no longer costs them all

**Plan**: 00404 (N1)
**Audience**: client projects with `transport.relay_enabled` or `nc_enabled`

When the per-event transport is on, the daemon binds one Unix socket per wired
hook event — thirty-one of them — alongside the legacy socket. Binding each one
is two filesystem steps: create the listener, then `chmod` it to `0o660`.

The first step was wrapped in a per-socket `except OSError: continue`, so a
failure there cost one event, which fell back to the legacy socket. The second
step sat one line OUTSIDE that guard. A failure there propagated out of the
bind loop, out of `start()`, and took **the whole daemon startup** with it.

**The window is real rather than theoretical.** That same method begins by
`shutil.rmtree`-ing the events directory, so a second daemon starting
concurrently for the same project can delete the socket in the moment between
the bind and the `chmod`. CI caught it exactly that way — a `FileNotFoundError`
on `subagent-start.sock` that failed one Python version and passed two, which
is the signature of a race rather than a version difference.

**The blast radius was the surprising part.** A reproduction that fails a
single `chmod` reported:

```text
E       assert 0 == (31 - 1)
```

Not "one socket lost" — all thirty-one. The per-socket `continue` immediately
above made the damage LOOK like one event, and the traceback alone left that
impression.

**What changes.** The `chmod` moved inside the same guard, so securing a socket
shares the best-effort contract that binding it already had: one event drops to
the legacy socket, the other thirty keep theirs, and startup completes.

**A socket that cannot be secured is skipped, not served.** The tempting fix is
to log the failure and keep the socket anyway. Without the `chmod` it carries
umask-derived permissions instead of the intended `0o660`, which trades a
security regression for an availability gain the legacy socket already provides
for free.

**It is also unlinked, not merely closed.** `asyncio` leaves a Unix socket file
on disk when its server closes, so closing alone would leave a path that looks
like a working socket with nothing behind it — harder to diagnose than its
absence.

**Nothing to do.** No configuration changes; a daemon that was starting
successfully will carry on doing so. The fix matters when two sessions start a
daemon for the same project at once, where the failure was previously total and
silent.
