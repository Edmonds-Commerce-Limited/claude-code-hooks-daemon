# Callout: an upgrade keeps running the opt-in handlers that were running before it

**Plan**: 00474
**Audience**: everyone

When a rule change would stop opt-in handlers that your project was running, `upgrade.sh` now writes `enabled: true` for each of them into `.claude/hooks-daemon.yaml`. It edits the file as text (comments, layout and line endings are kept) and replaces it atomically; the summary then names each restored handler, says why, and how to undo it: set the handler's `enabled: false`, or delete its block.

**The restored handlers do not run until the daemon is restarted.** This step runs after the upgrade has already restarted the daemon, so the running daemon and the guidance it generated at that start still have them off. The summary prints a `RESTART THE DAEMON` warning with the command (`.claude/hooks-daemon/bin/hooks-daemon restart`); run it, then review the handlers it kept and disable any you did not want.

Nothing is written, and the summary prints the YAML to add by hand as before, when the file cannot be edited safely: an unusual layout, a permission error, a failed write, or a config you list under `write_protected_paths`. An older target that does not know `--apply` produces the same report without the write.

Also: `.claude/fake-values.yaml` is pre-filled with visibly fake examples for the kinds docs are likely to need, and the docs QA check `unlisted-fake-value` reports any registry entry that does not look obviously fake.
