# Callout: a wedged daemon now recovers, on its own and on `stop`

**Plan**: 00466
**Audience**: operators

A handler that never returns keeps running after the daemon has given up on
it (a "straggler"). Two changes stop that from leaving the daemon stuck:

- **Self-restart.** Once the oldest straggler has run
  `daemon.chain.straggler_restart_after_seconds` (default 120), or as soon as
  the straggler cap is reached, the daemon exits and the next hook call starts
  a fresh one. At the cap every event with a safety guard is refused, `Stop`
  included, so an agent would otherwise loop on a blocked `Stop` until the
  restart. `health` reports `degraded` with the `stragglers` reason, the
  count, the oldest age and `at_capacity`. Setting
  `straggler_restart_after_seconds: null` disables self-restart.
- **`stop` and `restart` escalate to SIGKILL.** A handler holding the GIL
  cannot act on SIGTERM, so after SIGTERM's grace period `stop` now sends
  SIGKILL. It signals only a process it has proven is THIS project's daemon
  server (by the `--project-root` on its command line, or its venv path): a
  stale PID file that now names another project's daemon is cleaned up
  without signalling it, and a daemon whose project cannot be determined is
  not signalled at all (`stop` exits 1 and says so).

`health` also reports `degraded` for two other reasons that leave every guard
on: `chain_deadline` (see release note 41) and `project_handlers`, when a
project handler failed to load, with the file and the reason.
