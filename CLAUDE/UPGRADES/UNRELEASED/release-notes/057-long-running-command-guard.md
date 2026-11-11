# Callout: new opt-in `long_running_command_guard` keeps long commands out of the foreground

**Plan**: 00602
**Audience**: client projects

A command run in the foreground of the main thread blocks the session: messages from the owner and from other agents wait until it ends. The new `long_running_command_guard` PreToolUse handler denies a foreground Bash call that looks long and gives the exact `run_in_background` form, with a pointer to the Monitor tool for waiting on a condition.

- A `timeout N` wrapper with N above `threshold_seconds` (default 30) is the main flag, since a timeout of minutes means the command runs for minutes. A wait loop (`until`/`while` with `sleep`), `sleep N` above the threshold, and a known-slow program (test suites, QA runs, builds, installs, `gh run watch`) are denied too.
- A foreground command that is not known to be fast and carries no timeout gets an advisory (`R-LONG-RUNNING-NO-TIMEOUT`), never a deny.
- Never judged: a call with `run_in_background: true`, a command ending in `&`, a `timeout` at or below the threshold, short commands, and every sub-agent call.
- Ships **off**. Enable it with `handlers.pre_tool_use.long_running_command_guard.enabled: true`; options are `mode` (`deny`, `advise`, `off`), `threshold_seconds`, `extra_slow_patterns`, `extra_fast_programs` and `exempt_patterns`.
- One call that must block opts out with `MUST_RUN_FOREGROUND_BECAUSE="reason"; <command>`; a placeholder reason is not honoured.

Rule IDs: `R-LONG-RUNNING-WAIT-LOOP`, `R-LONG-RUNNING-TIMEOUT`, `R-LONG-RUNNING-SLEEP`, `R-LONG-RUNNING-SLOW-COMMAND`, `R-LONG-RUNNING-NO-TIMEOUT` (see `explain-rule`). Details: [Handler Reference](../../../../docs/guides/HANDLER_REFERENCE.md#long_running_command_guard).
