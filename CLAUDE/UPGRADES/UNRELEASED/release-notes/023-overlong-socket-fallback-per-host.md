# Callout: over-length socket paths are not-live, and the fallback paths are per host

**Plan**: 00483
**Audience**: everyone

When a project path is so long that the daemon's socket falls back to a short directory (`$XDG_RUNTIME_DIR`, `/run/user/<uid>` or `/tmp`), two things change.

- The start-up liveness check now reports an over-length socket path as not live, instead of "indeterminate". Previously `start` refused with a false "socket exists but its liveness is indeterminate" message when the path did not exist.
- The fallback socket, PID file, log and per-event socket directory names now carry a short hash of the hostname, so two hosts sharing one filesystem no longer share (and clobber) the same files. The name changes from `hooks-daemon-<hash>.sock` to `hooks-daemon-<hash>-<hosttag>.sock`, and from `hooks-daemon-<hash>-events` to `hooks-daemon-<hash>-<hosttag>-events`.

A project whose natural socket path fits is unaffected: its paths do not change. A project that uses the fallback gets new paths on upgrade. Restart the daemon after upgrading (the upgrade does this); the old `hooks-daemon-<hash>.*` files in the runtime directory are orphaned and can be deleted.
