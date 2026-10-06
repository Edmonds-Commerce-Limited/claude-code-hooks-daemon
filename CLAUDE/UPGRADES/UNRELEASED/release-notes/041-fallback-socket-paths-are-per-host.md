# Callout: the short-path fallback socket, PID file, log and events directory are per host

**Plan**: 00483
**Audience**: everyone

When a project path is so long that the daemon's paths fall back to a short directory (`$XDG_RUNTIME_DIR`, `/run/user/<uid>` or `/tmp`), the fallback names now carry a short hash of the hostname. Two hosts sharing one filesystem used to resolve the same fallback socket, PID file, log and per-event socket directory and clobber each other.

- The socket, PID file and log change from `hooks-daemon-<hash>.<ext>` to `hooks-daemon-<hash>-<hosttag>.<ext>`.
- The per-event socket directory changes from `hooks-daemon-<hash>-events` to `hooks-daemon-<hash>-<hosttag>-events`.

A project whose natural paths fit is unaffected: nothing changes for it. A project on the fallback gets new paths.

The upgrade handles this itself. It restarts the daemon, and it redeploys every hook forwarder from the new release and regenerates it from config (Step 8 of `upgrade_version.sh`, and the same redeploy on the already-up-to-date path), so a forwarder that baked the old events directory (the relay guard or the `nc` rung) is rewritten with the new one. No manual step is needed. The old `hooks-daemon-<hash>.*` and `hooks-daemon-<hash>-events` entries in the runtime directory are orphaned and can be deleted.
