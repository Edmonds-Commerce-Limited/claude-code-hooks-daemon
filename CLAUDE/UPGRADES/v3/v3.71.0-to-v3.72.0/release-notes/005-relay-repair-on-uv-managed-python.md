# Callout: the automatic relay repair now starts when the daemon runs on a uv-managed Python

**Plan**: 00474
**Audience**: operators

When `daemon.transport.relay_enabled` is on and the relay binary is missing or cannot run, the session-start relay check starts a detached repair in the background. It started that process with `os.posix_spawn(..., setsid=True)`.

CPython builds installed by `uv python install` (python-build-standalone) lack `POSIX_SPAWN_SETSID`, so on those interpreters that call raised `NotImplementedError: posix_spawn: setsid unavailable on this platform`. Builds from the operating system's packages do not have this problem. The error was not an `OSError`, so the repair never started and the session-start check failed instead of reporting.

The repair process is now started through `subprocess.Popen` with `start_new_session=True`, which gives it its own session on every CPython build. Nothing to do on upgrade: a missing relay binary is repaired at the next session start.
