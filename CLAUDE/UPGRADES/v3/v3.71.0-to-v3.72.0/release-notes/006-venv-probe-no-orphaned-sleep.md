# Callout: probing a venv interpreter no longer leaves a stray `sleep` process behind

**Plan**: 00474
**Audience**: operators

When the daemon's launcher has no cached venv interpreter, it probes each candidate under a watchdog. The watchdog waits out a timeout with `sleep` and is cancelled as soon as the candidate answers.

About one probe in 25 could cancel the watchdog too early, after it had started its `sleep` but before it had recorded that process. The `sleep` then outlived the watchdog and stayed attached to PID 1 for the whole timeout, which can be many hours when `HOOKS_DAEMON_VENV_PROBE_TIMEOUT` is set high.

The watchdog now finds its `sleep` through the shell's job table, which holds it from the moment it starts, so no `sleep` survives. Nothing to do on upgrade. A stray `sleep` left by an earlier version can be killed safely.
