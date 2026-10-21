# Task 2a (relay loud): report (PARTIAL, unit 1 of 2)

Status: N525 is implemented and committed. N523 has not been started. The first
agent reached its context budget, so a handoff is at
`untracked/scratch/261021-a1306833dfcb7ad3d-handoff.md` in the worktree. The agent
that finishes this task extends this report.

## Unit 1: N525, `transport on` reports a binary it provisioned (commit 036540c88)

- `ensure_relay_binary` now returns a `RelayProvision(failure, route, binary)`
  instead of `str | None`, so the route that `deploy_relay_if_configured`
  returned reaches the toggle.
- `ToggleOutcome` carries `provisioned_route` and `provisioned_binary`, and both
  are recorded in the toggle state file.
- `cmd_transport` prints `transport on: relay binary provisioned via <route> at <path>`
  whenever a binary was written. "nothing to do" can no longer print in that case.
  The failure branch no longer claims "No state was changed" after a provisioning.

**Departure from the brief:** when the config already holds `relay_enabled: true`
and the forwarders are current, a provisioned binary is now VERIFIED with the
transport probes. It is not reported as an unverified no-op. The guards start
using the relay from the next hook, so `verified=None` would claim a relay rung
nobody checked. No restart happens, because the forwarders and the per-event
listeners are unchanged.

TDD red output, recorded before the implementation:

- `tests/unit/install/test_transport_toggle.py`:
  `ImportError: cannot import name 'RelayProvision' from 'claude_code_hooks_daemon.install.transport_toggle'`
- `tests/unit/daemon/test_cli_transport.py`: `3 failed, 10 passed`, with
  `TypeError: ToggleOutcome.__init__() got an unexpected keyword argument 'provisioned_route'`

Green: 63 passed across both files, and mypy is clean on the two source files.
Targeted QA has not run yet.

## Unit 2: N523, not started

The design and the status exit-code decision are in the handoff. The decision
is to keep status's exit code liveness-only, because it is documented that way
and `health` is the non-zero-on-degrade command. The relay warning is printed
loudly instead.

## Unit 2 (status)

Commits: f661c34c0 (shared helpers) and bb0b4a815 (cmd_status warning).

- `install/relay_deploy.py`: `missing_configured_relay_binary(project_root, transport)`
  returns the path, or None when the relay is disabled or the binary is an executable
  file. `relay_binary_missing_warning(binary, fix_command)` returns one line naming the
  path, the fallback transport and `Fix: <command>`. The SessionStart handler imports both.
- `cmd_status`: the transport config load is now `_load_status_transport_config`, done once
  before the liveness branch. `_print_relay_binary_warning` prints a `WARNING: relay is enabled but its binary is missing or not executable: <path> ... Fix: bin/hooks-daemon transport on` line in both the NOT RUNNING and RUNNING branches.
- Exit code unchanged: liveness only (0 running, 1 not running), as the handoff decided.
- Existing test `test_no_shortfall_warning_when_every_wired_event_is_bound` asserted no
  "WARNING" with the relay enabled and no binary; it now provides an executable binary so
  it still tests only the listener shortfall.
- RED: `test_relay_deploy.py` failed at collection with
  `ImportError: cannot import name 'missing_configured_relay_binary'`;
  `test_cli_status_relay_binary_warning.py` gave `2 failed, 2 passed` (the two silent
  cases passed).
- GREEN: 41 passed across the three touched test files and 178 across the other status
  and CLI test files. mypy is clean on both source files.
