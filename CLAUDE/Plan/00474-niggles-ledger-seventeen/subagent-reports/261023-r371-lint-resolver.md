# r3.71 N538: one linter-executable resolver for both lint gates

Branch `worktree-r371-lint-resolver`, base `d70563b52`.

## Was N538 real?

Yes. `StagedLintGateHandler._resolve_executable` searched only the interpreter
`bin` and then `PATH`. `LintOnEditHandler._resolve_executable` searched the
file's workspace `bin_dirs` first (for example `node_modules/.bin` and
`vendor/bin`). Take a declared sub-project with its own copy of a linter while
a global copy sits on `PATH`: `lint_on_edit` launched the sub-project's copy,
and the commit gate launched the `PATH` copy for the same file.

Verified RED before the fix. In
`test_that_binary_is_the_subprojects_own_pinned_copy`, the gate's assertion
failed because the gate returned the `PATH` copy.

## Tests

- `tests/unit/handlers/test_lint_gates_subproject_executable.py`

  - `TestSubProjectLinterExecutable::test_both_gates_launch_the_same_linter_binary_for_a_subproject_file`
  - `TestSubProjectLinterExecutable::test_that_binary_is_the_subprojects_own_pinned_copy`

  The fixture is a `frontend/` sub-project with a `package.json` and its own
  `node_modules/.bin/n538-fake-linter`, plus a second copy on a `PATH` that
  the test sets. The test then reads which executable each gate passes to
  `subprocess.run`.

- `tests/unit/strategies/lint/test_common.py::TestResolveLintExecutable` has
  6 tests for the shared resolver: an absolute path is returned unchanged, the
  workspace copy beats `PATH`, bin dirs are searched in order, the interpreter
  `bin` comes before `PATH`, `PATH` is the fallback, and an absent tool gives
  None.

## Fix

This follows the `ModuleContext.working_dir` pattern: there is now one shared
resolver, and both gates call it.

- `src/claude_code_hooks_daemon/strategies/lint/common.py:39`
  `resolve_lint_executable(executable, bin_dirs) -> str | None`. The search
  order is the workspace bin dirs, then `INTERPRETER_BIN_DIR` (`:36`, moved
  here from both handlers), then `PATH`. An absolute path is returned
  unchanged.
- `src/claude_code_hooks_daemon/handlers/post_tool_use/lint_on_edit.py:367`
  `_resolve_executable` now delegates to it. The method is kept because tests
  patch it.
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/staged_lint_gate.py:441`
  `_resolve_executable(executable, workspace_bin_dirs)` delegates to it, with
  `workspace_bin_dirs` now required. `:381` passes the staged file's resolved
  `workspace.bin_dirs`. The workspace was already resolved there for
  `working_dir`.
- Each handler's own `_INTERPRETER_BIN_DIR` copy is removed, along with the
  `shutil` and `sys` imports that only it used.

## Additional fix: a defect already on the base

`d70563b52` merged
`tests/unit/core/test_data_layer.py::test_a_failed_legacy_import_keeps_the_loaded_registry_and_its_notices`,
which calls `blockage_marker.write_marker`. That function no longer exists, so
ruff reported F821 and pyright reported `reportUndefinedVariable` at `:278`,
failing QA. The call now writes the legacy marker shape with
`write_json_atomically`, as the module's `_legacy_marker` helper does. Other
r3.71 worktrees based on `d70563b52` will hit the same failure.

## QA

- First run: 37/41. Two failures were the `test_data_layer.py:278` defect.
  The third was
  `test_safety_handlers_hostile_input_performance.py::...test_bash_command[star_star_slash_star]`,
  a timing test that failed while the host was loaded. That file passes alone
  (43 passed) and doesn't touch the changed code.
- Final run on a clean tree:
  `llm_qa.py changed --range d70563b52..HEAD --allow-unmapped` gave
  **`QA: 41/41 PASSED`**.
- Targeted runs: every lint_on_edit and staged_lint_gate test file, both
  sub-project gate files, `test_ansible_governing_config_gates.py`,
  `test_cli_enforcement_status.py` and `test_common.py` gave 363 passed.
  mypy found nothing in the 3 changed source files.
- The QA mapper reported `lint_on_edit.py` and `staged_lint_gate.py` as
  unmapped (too-broad), so the coordinator's full gate must cover them. Their
  test files were run explicitly above.

## Commits

- `d12729bc6` Plan 00474: N538 both lint gates resolve the linter through one
  function
- `6c301848c` Plan 00474: restore the undefined write_marker call in
  test_data_layer
- The commit adding this report is the head; see the reply for its sha.
