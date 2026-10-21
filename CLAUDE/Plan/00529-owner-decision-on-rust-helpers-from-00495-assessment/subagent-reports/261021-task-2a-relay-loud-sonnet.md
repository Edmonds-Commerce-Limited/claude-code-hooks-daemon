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
