# Callout: ccy supervisor plugin API

**Plan**: 00487
**Audience**: client projects

**Beta.** The plugin API is ready for real-world testing but not yet proven in long-running use. Its supervisor
side passed a live test (loading, status, notices, restart, and a raising, hanging or printing plugin never taking
the session down); the remaining ccy launcher checks are handed to the launcher's own repository. Session limits (`--max-age`,
`--run-for`, `--until`) need ccy 3.82.1 or later, or `ccy --supervise` on an older ccy. Report hooks-daemon problems
as issues on this repository.

The ccy supervisor can now be extended without forking it: a launcher names a
stdlib-only plugin with `--plugin <name>=<worker.py>` and its `on_idle` hook is asked at the very end of the idle cascade, after every built-in family. A plugin that fails in any way (a refused file, an exception, an overrun, a wedged worker, a bad result) is disabled for the rest of the supervisor process, the worker is restarted without it where needed, and the session is told once by a fixed-template plugin notice; the session always starts. A plugin can also return `ExitForRestart`, which makes the supervisor type `/exit` at an idle point, write `.claude/ccy/state/restart-request.json` and exit with status 75 so the launcher can relaunch with `--resume <id>`. The contract, failure path, exit status and a test harness for plugin authors are in `CLAUDE/development/CcySupervisor.md`. A plugin can also return `Notify(RESTART_SOON, minutes)` or `Notify(DEADLINE_REACHED)` to ask for a fixed-template session notice (the plugin supplies no text; each kind is rate-limited), and after an exit-for-restart the resumed session is told once, by the supervisor, that it was restarted and which Claude Code version it is now on, using a separate `.claude/ccy/state/restarted.json` marker the launcher must leave in place. Plugin code never runs in the PTY host: the worker's reply channel is private to it, and while the worker is silent the host decides with the built-in families only. A launcher whose plugin keeps asking to restart a session that will not exit is backed off for ten minutes and, after three abandoned attempts, the plugin is disabled with a notice. Using plugins needs a ccy relaunch, because the flags and the registry are host code.
