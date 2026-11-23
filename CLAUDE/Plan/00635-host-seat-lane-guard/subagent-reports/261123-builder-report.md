# Plan 00635 builder report

Branch `plan-00635-host-seat-lane-guard`, off `origin/main` at `6ac79ca2b`.

## Built

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/host_seat_lane_guard.py`:
  `HostSeatLaneGuardHandler`, priority 21 (inside the Safety band 10-21, which
  was not widened; it runs before `long_running_command_guard` at 40), rule
  `R-HOST-SEAT-LANE`, `mode: advise` by default (`off | advise | block`), option
  `extra_lane_patterns`. Its structure follows `human_approval_check`: the
  injected `_team_seat`, a lazy `_resolver`, silence for any failure before
  arming, and the mode's refusal for any failure after it.
- Arming is `duty_gate(hook_input, context, duty="host")`:
  - With no `TEAMCHAT_RUNTIME` on the payload it does not probe, and nothing
    changes.
  - Absent, no teams, exit 69, a sub-agent, worker, coordinator, or another
    declared duty: silent.
  - Declared `host` in ANY team: armed.
  - `ROLE_UNKNOWN` (unresolved probe or a null duty): armed. This follows the
    settled Q64 D3 text in section 15, which overrides section 4's "B7 goes
    quiet" recommendation. The first refusal in a session adds "the teamchat
    whoami probe gave no answer".
- Classification reuses `classify` and `FindingKind` from
  `utils/long_running_command.py`:
  - `DEFAULT_SLOW_PATTERNS` is now split into named groups (`TEST`, `BUILD`,
    `MAKE`, `QA`, `INSTALL`, `CONTAINER`, `WATCH`). The default is still their
    concatenation, so `long_running_command_guard` behaves the same.
  - The lane takes the test, build and QA groups, adds lint tools, `make` alone
    or `make` with a test/build/lint target, and scripts named for test, QA or
    lint. It never touches installs, docker, `make deploy`, log tails or
    `gh run watch`.
  - `classify(..., include_background=True)` is new, so `pytest &` is judged.
    The lane policy's threshold is 0, so `timeout 20 pytest` is still judged.
- Refusal text is fixed and never echoes the command. It names the lane: "run
  it in a worker seat".
- The guard opens no file under the run dir or kit; that is tested the same way
  as in `human_approval_check`. There are no v1 verbs or fixtures, and no
  approval or bypass path.

## Found and fixed in what I touched

- `nice -n 19 pytest` was peeled to a program named `19`. As a result
  `long_running_command_guard` never saw that slow run (and neither would this
  guard). Wrapper value options are now peeled for `nice`, `ionice` and `sudo`,
  with a regression test in `tests/unit/utils/test_long_running_command.py`.
- Release notes: `090` exists twice across remote branches (a collision
  elsewhere). This plan takes `091`.

## Registration and drift lists

Updated:

- constants: `HandlerID`, `Priority`, `RuleID`
- `init_config.py`
- both hooks-daemon yaml files
- `HANDLER_REFERENCE.md`
- `config-changes/v3.77.0.yaml`
- release note `091-host-seat-lane-guard.md`
- `test_claude_md_guidance_coverage`
- `test_pretooluse_fail_closed_tagging` (`_AUDITED_BLOCKING_ONLY_REASONS`)
- `test_blocking_handler_evasion`
- `CLAUDE.md`: the marker and the rule row
- `.claude/HOOKS-DAEMON.md`: the row and the count, inserted by hand to the
  generator's shape because the markdown formatter reflowed the whole file on
  Edit

Not updated:

- `_EXPECTED_MAIN` in `test_handler_scope_defaults.py`: no handler scope is
  declared.
- The CONTRIBUTING.md and HANDLER_DEVELOPMENT.md band tables: the band is
  unchanged.

## QA (targeted only, nice -n 19)

- ruff, black, and mypy on the changed source: clean.
- `check_magic_values.py`: 0 violations. `audit_error_hiding.py`: clean.
- pytest over the new and changed tests plus the drift-list integration tests:
  see the result line appended below.

## Left

- Live verification in a host-duty seat, then the owner's ruling to promote to
  `block` (Task 2.1).

Result: 3391 passed (tests/unit/handlers/pre_tool_use/test_host_seat_lane_guard.py, tests/unit/utils/test_long_running_command.py, test_long_running_command_guard.py, test_pretooluse_fail_closed_tagging.py, test_blocking_handler_evasion.py, tests/unit/constants, tests/unit/daemon/test_init_config.py, tests/unit/qa/test_audit_error_hiding.py, and integration test_claude_md_guidance_coverage, test_handler_scope_defaults, test_acceptance_*, test_all_handlers_response_validation, test_config_changes_manifest_examples, test_dogfooding_config, test_example_config, test_handler_config_blocking, test_handler_instantiation, test_handler_reference_check, test_handlers_do_not_match_prose, test_every_handler_response_validates, test_generated_docs_are_path_agnostic, test_doc_truth_check).
