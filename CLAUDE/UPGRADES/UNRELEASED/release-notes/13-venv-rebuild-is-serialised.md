# Callout: two daemons starting at once no longer rebuild the same venv

**Plan**: 00362
**Audience**: operators

A venv build or rebuild now runs under a lock beside the venv
(`untracked/.venv-bootstrap.lock`, `flock` by default with a `mkdir` fallback),
so a second daemon start — a host shell next to a container, two terminals in
one project, or `hooks-daemon repair` alongside a start — waits for the first
build and reuses it instead of deleting it mid-copy. The wait is bounded
(`HOOKS_DAEMON_VENV_LOCK_TIMEOUT`, 120s) and says which lock it is waiting on;
a venv that is already fresh is used without touching the lock at all.
