# Callout: the upgrade's stale-venv cleanup no longer depends on the host's `python3`

**Plan**: 00546
**Audience**: everyone

The cleanup of stale `venv-*` directories at the end of an upgrade used to run `python3` from `PATH`. On a host whose `python3` is older than the daemon supports (3.9), that crashed on import, the failure was printed as a routine "Kept venv-\* entries" line, and the upgrade reported success. The cleanup now runs on the current venv's own interpreter, falling back to the `HOOKS_DAEMON_PYTHON` the upgrade already resolved, and never to a bare `python3`. When neither is usable, or the listing step fails, the upgrade prints a `WARNING: stale venv-* cleanup SKIPPED` block to stderr naming the reason and leaves the stale entries in place (`bin/hooks-daemon list-venvs` shows them). The warning does not fail the upgrade, since the new daemon is already verified running by then.
