# Plan 00608: symlinked-project teardown defect (CI run 43785525213)

## Hypothesis: proven

Local run of `tests/integration/test_a_daemon_of_a_symlinked_project_is_stoppable.py` reproduced `OSError [Errno 39] Directory not empty: '.../untracked'` at teardown. The left-over tree held `untracked/relay-repair/<key>.state` with `pid=<child>`, `status=failed`, `detail=FileNotFoundError ... .claude/hooks`: the detached repair child, started by the daemon at start-up (relay on by default, no binary in the temp project), was still creating files and writing its state while the test tore the tree down.

## Product defect: real

Daemon stop did not end the repair the daemon started. Fixed test-first:

- `install/relay_repair.py`: `spawn_owned` (like `spawn_detached`, but registered), `stop_owned_repairs` (SIGTERM then SIGKILL to the child's process group, each bounded by `Timeout.DAEMON_REPAIR_STOP_GRACE` = 1 s, reaped before returning; an unfinished `running` claim is withdrawn so the next start retries, a recorded result is kept), `owned_repair_pids`.
- `daemon/controller.py`: the daemon-start path passes `spawn_fn=spawn_owned`.
- `daemon/server.py`: `shutdown()` runs `stop_owned_repairs` (off the event loop, before closing the socket); deferred start-up steps not yet begun are skipped once shutdown began. The import is local (the install package imports server at load time).
- `constants/timeout.py`: `DAEMON_REPAIR_STOP_GRACE`; twice it fits inside `DAEMON_SHUTDOWN_AFTER_DRAIN_MARGIN`.
- Release note 080 updated.

## SessionStart path

Unchanged and still detached on purpose: its parent is a hook process that exits at once, so there is no owner to stop it, and the repair is meant to outlive the hook. Test `test_spawn_detached_is_not_owned` pins this.

## Residual, stated

A daemon killed with SIGKILL cannot end its repair, which then finishes on its own. A deferred step already running when shutdown begins is waited on only by the skip check, not blocked on.

## Proof

The symlinked-project test file is unchanged (relay on, no binary): 14 passed three times in a row. Unit: `tests/unit/install/test_relay_repair_owned.py` (11), plus server and controller tests.

## Other temp-project daemon test families

Each writes its own config (no shared helper): test_a_retried_hook_never_restarts_a_slow_start, test_config_integration, test_init_sh_daemon_down_read_only, test_init_sh_daemon_down_stop_bound, test_init_sh_pretooluse_fail_closed, test_relay_provision_sh, test_upgrade_sh_effective_handler_report, test_upgrade_sh_tmp_self_contained. The product fix covers all; none was changed.
