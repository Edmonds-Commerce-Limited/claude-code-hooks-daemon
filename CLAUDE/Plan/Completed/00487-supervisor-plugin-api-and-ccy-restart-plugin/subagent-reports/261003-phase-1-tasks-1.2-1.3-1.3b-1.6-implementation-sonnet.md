Phase 1 of Plan 00487 is built for Tasks 1.2, 1.3, 1.3b and 1.6, plus the plugin test harness. Tasks 1.4 (in-container `Restart`) and 1.5 (host half, `before_spawn`) are not started. All work is in `.claude/ccy/claude-supervise.py` (call it `S`) and `tests/unit/supervise/`. The supervisor is still stdlib-only. The design source is the owner-ruled draft in fedora-desktop Plan 00146; this report records where the build made a choice the draft left open.

## What was built

| Piece            | Where in `S`                                                                     | Notes                                                                                              |
| ---------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Loader           | `parse_plugin_spec`, `check_plugin_file`, `PluginHost`, `PluginRuntime`          | Host vets and never imports. The worker re-vets, then imports on a budgeted thread.                |
| Flags            | `_add_plugin_arguments`, `_parse_supervisor_flags`, `_parse_worker_plugin_flags` | One argparse definition serves host and worker. `_USAGE` and the module docstring updated.         |
| Status list      | `write_supervisor_status(plugins=...)`, `PluginHost.status_entries`              | `plugins` key is absent when no `--plugin` was given.                                              |
| Worker hooks     | `PluginRuntime.start/run_idle`, the block at the end of `decide_once`            | Gate: payload None, `NOOP`, no compaction signal, `MONITOR`, `can_inject`, no own line pending.    |
| Wire format      | `TickOutcome` + `_outcome_to_json` / `_outcome_from_json`                        | Four new fields, defensive decoders, legacy JSON decodes with empty defaults.                      |
| Exit for restart | `RestartCoordinator`, `EXIT_STATUS_RESTART_REQUESTED = 75`                       | State file `.claude/ccy/state/restart-request.json`. `CCY_SUPERVISOR_STATE_DIR` overrides the dir. |
| Failure path     | `PluginFailure`, `handle_plugin_outcome`, `handle_worker_silence`                | Detect, disable (survives reload), recover, tell.                                                  |
| Notice family    | `Decision.WOULD_PLUGIN_NOTICE`, `render_plugin_notice`, machine queue            | Fixed templates, one per plugin, capped at 5, ranked with the operator signal.                     |
| Test harness     | `PluginTestHarness`, `PluginHarnessError`, `plugin_harness` fixture              | Real loader, no worker, raises with the traceback.                                                 |

Tests: `test_plugin_loader.py`, `test_plugin_worker_hooks.py`, `test_plugin_exit_for_restart.py`, `test_plugin_failure_path.py`, `test_plugin_harness.py`, with shared helpers in `_plugin_helpers.py`. The whole `tests/unit/supervise` directory passes. Three tests run a real worker subprocess over a real PTY: a raising plugin, an overrunning plugin, and a worker stopped with `SIGSTOP` inside a hook (a real wedge).

## Choices the draft left open

1. **Notices live in machine state, not in files.** The draft says the detector "writes a plugin-notice signal". Here a notice is an item in the `CompactStateMachine` queue (`plugin_notices_pending`), shipped to the host in `machine_state` like the audit backlog. A worker-detected failure and a host-detected one therefore use one queue and one dedupe (`plugin_noticed`, by name). No new sidecar suffix, no reaper change.
2. **Failures are cumulative and idempotent.** The worker re-sends its whole failure list on every tick. The host discards a reply that arrives after the read timeout, and with it any notice armed in that reply's machine state; re-sending means the next tick arms it again. `arm_plugin_notice` is a no-op for a plugin already told, and `PluginHost.record_failure` returns True only the first time, which is what gates the log line and the worker restart.
3. **`Restart` is not defined.** An `on_idle` that returns anything but `None` or an `ExitForRestart` is a `bad-result` failure. When Task 1.4 adds `Restart`, nothing existing changes meaning.
4. **Status states.** `failed` means never loaded (the host's vetting or the worker's loader). `disabled` means loaded and then turned off, by a runtime failure or by `--disable-plugin`. The `reason` is always a closed value.
5. **The wedge check runs before the in-process fallback.** The first version of the live wedge test showed why: when the worker is stopped inside a hook, the tick falls back to the in-process decision, which loads the same plugin in the host and runs the same hook there. `handle_worker_silence` therefore runs first and disables the culprit. It also needs a fresh clock reading, not the tick's: the host has just waited up to 2 seconds for the worker.
6. **`/exit` is tracked as an own line.** `RestartCoordinator.request` calls `mark_own_line_typed("/exit")`. If the child ignores it and the hold is abandoned, the supervisor's ordinary own-line follow-up can still press Enter later, and the session then simply ends with the child's own status (no request file, so the launcher does not relaunch). Documented.
7. **State directory override.** `CCY_SUPERVISOR_STATE_DIR` redirects `.claude/ccy/state/`. The live tests need it so a real worker subprocess does not write into the worktree.

## Known limits, all documented in `CcySupervisor.md`

- `cached_own_session_ids()` only grows. A `/clear` or a resume that introduces a second id makes every later exit-for-restart refuse until the supervisor is relaunched. That is the draft's "exactly one" rule applied literally.
- A plugin that holds the GIL in C code can stall the host when it runs through the in-process fallback. The thread budget cannot return from such a call. This is the draft's own stated limit; the fallback was asked for explicitly in the dispatch.
- Editing a plugin file does not change the content hash the worker reload watches, so the worker must be restarted once to pick the edit up.
- The flags and registry are host code, so using plugins needs a ccy relaunch. This task did not restart the live supervisor and did not touch `.claude/ccy/settings.json`.

## Not done in this dispatch

- Tasks 1.4 and 1.5 (out of scope by the dispatch).
- The Task 1.7 worker-reload verification against a live supervisor (the dispatch forbids restarting it).
- `llm_qa.py changed` reports `.claude/ccy/claude-supervise.py` and `tests/unit/supervise/conftest.py` as unmapped (`too-broad`: they reach more than 40 test files), which fails the run unless `--allow-unmapped` is passed. The whole `tests/unit/supervise` directory was run instead.
