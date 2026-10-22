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

## Unit 2 (SessionStart) and QA

Commit fe50f7d57: new handler `handlers/session_start/relay_binary_checker.py`
(`RelayBinaryCheckerHandler`) and release note 011.

- No existing SessionStart handler fitted (as the handoff found), so this is a new
  handler modelled on `unproven_venv_advisor`. Tags ADVISORY, ENVIRONMENT,
  NON_TERMINAL; `get_claude_md()` is None; matches every session start.
- It loads `<root>/.claude/hooks-daemon.yaml`, calls `missing_configured_relay_binary`,
  and prints one line, `WARNING: ` + `relay_binary_missing_warning(binary, daemon_cli_command("transport", "on"))`, the same text `status` prints.
  Silent when the relay is disabled, the binary is executable, there is no config
  file, or ProjectContext is uninitialised.
- **Departure from the model handler:** an unreadable config (ValidationError,
  OSError, ValueError) is REPORTED as a WARNING naming the config path. The model
  handlers degrade to `Config()` defaults, which here would read as "relay
  disabled" and say nothing. That is the silent fallback the owner ruled out.
- Registration: `HandlerID.RELAY_BINARY_CHECKER`, `Priority.RELAY_BINARY_CHECKER = 72`
  (shares the slot with unproven_venv_advisor; 73 must stay last),
  `session_start/__init__.py`, `init_config.py`, `.claude/hooks-daemon.yaml`,
  `.claude/hooks-daemon.yaml.example` (required by `test_example_config`, not in the
  handoff list), `.claude/HOOKS-DAEMON.md` (regenerated with `generate-docs`, not
  hand-edited: a hand edit set off the markdown formatter across the whole file),
  `config-changes/v3.71.0.yaml` entry, and the T4 exemption in
  `test_claude_md_guidance_coverage.py`. Acceptance test: one CONTEXT case.
- RED (before the handler existed): `test_relay_binary_checker.py` failed at
  collection with `ModuleNotFoundError: No module named 'claude_code_hooks_daemon.handlers.session_start.relay_binary_checker'`.
- GREEN: 10 passed. Registration and config tests (guidance coverage,
  config-changes manifest examples, config migrations, example config, template
  priorities, upgrade effective-handler report, released-unreleased tree, stop chain,
  init_config, registry, constants, all session_start handler tests): 2094 passed,
  1 failed (`test_example_config_includes_all_library_handlers`, fixed by the
  `.yaml.example` entry; rerun 19 passed). mypy clean on the handler.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/011-relay-binary-problems-are-reported-not-silent.md`
  covers N525 (provisioned binary reported and verified), the status WARNING with
  the unchanged exit code, and the SessionStart advisory.
- Not done: a live daemon restart in this worktree to see the handler load. The
  registry tests load it from the package.

### Targeted QA (`llm_qa.py changed --allow-unmapped`, at fe50f7d57)

Verdict: 36/40 passed, 2 failed, 2 not meaningful (because of the 2 failures).
changed_tests ran 4262 passed, 0 failed, 5 skipped; project_handlers 238 passed.
Both failures are in the status unit's files, not in this unit's, so they were
left for that owner and are reported here:

1. `format`: black reformatted `tests/unit/daemon/test_cli_status_event_listeners.py`
   (auto-fixed). The fix is in the working tree, uncommitted.
2. `error_hiding` `return-none-on-error` at `daemon/cli.py:1538`,
   `_load_status_transport_config`: it returns None on FileNotFoundError or
   PydanticValidationError. This code existed inline before bb0b4a815; extracting it
   into a function that returns `TransportConfig | None` is what the checker now
   sees. A fix that also fits the owner's rule: when the config is invalid
   (not merely absent), print a status WARNING that the relay state is unknown,
   as `relay_binary_checker` does, instead of returning None silently.

Follow-up: black reformat committed; _load_status_transport_config now returns a frozen _StatusTransport(config, problem), so an invalid config prints a transport-config-unreadable WARNING in both status branches (exit code still liveness only) and no except block returns None.
Red first (2 failed, 5 passed), then green; mypy cli.py clean; llm_qa format error_hiding lint type_check 4/4 PASSED. Note: get_project_path already exits on an invalid config, so the branch is reached only on a load race; tests patch Config.find_and_load.
