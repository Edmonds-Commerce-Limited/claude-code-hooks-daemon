# Callout: ccy supervisor plugin API

**Plan**: 00487
**Audience**: client projects

The ccy supervisor can now be extended without forking it: a launcher names a
stdlib-only plugin with `--plugin <name>=<worker.py>` and its `on_idle` hook is asked at the very end of the idle cascade, after every built-in family. A plugin that fails in any way (a refused file, an exception, an overrun, a wedged worker, a bad result) is disabled for the rest of the supervisor process, the worker is restarted without it where needed, and the session is told once by a fixed-template plugin notice; the session always starts. A plugin can also return `ExitForRestart`, which makes the supervisor type `/exit` at an idle point, write `.claude/ccy/state/restart-request.json` and exit with status 75 so the launcher can relaunch with `--resume <id>`. The contract, failure path, exit status and a test harness for plugin authors are in `CLAUDE/development/CcySupervisor.md`. Using plugins needs a ccy relaunch, because the flags and the registry are host code.
