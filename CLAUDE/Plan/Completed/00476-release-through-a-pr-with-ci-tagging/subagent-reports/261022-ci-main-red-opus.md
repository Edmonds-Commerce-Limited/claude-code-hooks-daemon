# Main CI red: three causes fixed, plus a fourth found on the base

Branch worktree-ci-main-red-fix, based on ab5b4ec48. Fix commit 875b021ad, Black follow-up 54aa51cbd (head is the commit that adds this report, see the reply).

## 1. Background tracker roundtrip (3 tests)

- Cause: Plan 00501 Phase 2 made `session_policy` read the per-session mode registry through `ProjectContext`. The test never initialised it. A real daemon always does, so the gap was in the test, not the handler.
- Decision: production code is unchanged. The RuntimeError is the intended fail-fast and must stay.
- Fix: an autouse fixture in `tests/integration/test_background_tracker_harvester_roundtrip.py` that depends on the shared `project_context` fixture from `tests/integration/conftest.py`.
- Red: CI log (3 failures, "ProjectContext not initialized"). Green: all 3 pass locally.
- Other callers: the integration and unit suites that reach `autonomy_allowed` already pass in the relay/install sweep, and the QA run was 41/41. No other test had the gap.

## 2. Hand-rolled temp name in install/relay_repair.py

- Cause: Plan 00529 spelled `.{name}.{pid}.tmp` itself in `_write_state`.
- Fix: `unique_temp_path(path)`. Also added `install/relay_repair.py` to `_WRITER_MODULES` in `tests/unit/utils/test_temp_names.py`, so the module is held to using the helper.
- Red: `test_no_source_file_spells_a_pid_keyed_temp_name` failed with the offender list. Green after the fix.

## 3. shellcheck SC2093 in every deployed forwarder

- Cause: the relay guard ran `exec` under `shopt -s execfail` with the fallback code after it. shellcheck cannot model execfail.
- Fix in the template (`build_relay_guard_block` in `src/claude_code_hooks_daemon/install/forwarder_generator.py`): the exec moves into a local function `_rl_exec_relay` whose last command is the exec, and the guard calls it with `"${BASH_SOURCE[0]}"`. Nothing follows the exec inside the function, so the warning has nothing to name, and no directive is used. The execfail fallback is unchanged: a failed exec returns from the function and the script reaches the python forwarder.
- Behaviour check: in bash, with execfail, a failing exec in a function returns rc 127 and execution continues. An env prefix on the function's exec reaches the exec'd process.
- Regenerated the 27 deployed forwarders with `python -m claude_code_hooks_daemon.install.forwarder_generator --project-root /workspace --hooks-dir <worktree>/.claude/hooks`. This keeps the baked main-checkout root, as 516c295f8 did. Nothing was hand-edited.
- Tests: updated the two string-pinning tests in `tests/unit/install/test_forwarder_generator.py` and added `test_guard_block_exec_is_the_last_command_of_its_function`.
- Red: `test_shell_assets_are_clean` showed SC2093 on every forwarder. Green: it passes, and shellcheck reports no SC2093 on `.claude/hooks/*`.

## 4. Extra: reference config omitted focus_mode_trigger

- Found while running `tests/unit/install`: `test_every_registered_handler_is_listed_for_its_event` failed on the base. Plan 00501 Phase 3 registered `focus_mode_trigger` but `.claude/hooks-daemon.yaml.example` did not list it, so main would have been red on it too.
- Fix: added the entry (enabled, priority 41), copying the live config.

## Evidence

- Relay and forwarder tests plus `tests/unit/install` and the lint test: 2076 passed, 57 skipped, 1 failed. The failure was item 4, now fixed (`test_reference_config_completeness.py` 3 passed).
- Targeted QA: `QA: 41/41 PASSED` (`llm_qa.py changed --range ab5b4ec48..HEAD --allow-unmapped`). An earlier run flagged Black formatting in two test files; fixed in 54aa51cbd and rerun clean. The output is at untracked/scratch/qa-ci-red.txt in the worktree.
- Nothing was merged, main was not pushed, and the daemon was not restarted.
