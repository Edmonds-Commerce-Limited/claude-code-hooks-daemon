# r371 lint working-dir and dead-code fixes (release v3.71.0 review)

Branch `worktree-r371-lint-deadcode`, base `df6c44a3b`. Fix commit `3b00bc962`. The branch head is the commit that adds this report; get its sha from `git log -1` on the branch.

Source review: `untracked/agent-reports/auto/261023-164905-code-reviewer-a770739316e68cf5b.md`.

## D1: the two lint gates ran the linter from different directories

- **Real?** Yes. I reproduced it with a failing test before fixing anything. For a file in a declared sub-project `frontend/`:
  - `lint_on_edit` ran the linter from `<repo>/frontend`.
  - `staged_lint_gate` ran it from `<repo>`.
- **Tests** (new file `tests/unit/handlers/test_lint_gates_subproject_working_dir.py`):
  - `TestSubProjectWorkingDirectory::test_both_gates_run_a_subproject_file_from_the_same_directory`
  - `TestSubProjectWorkingDirectory::test_that_directory_is_the_declared_subproject_root`
- **Fix:** `ModuleContext.working_dir` is the one shared function. It now takes the file's resolved `Workspace` instead of a bare path (`src/claude_code_hooks_daemon/strategies/lint/module_context.py:66`). The bug happened because any path was accepted, so the gate could pass the repo root. A bare path is now a type error. Callers:
  - `staged_lint_gate` resolves the workspace with `resolve_workspace(self._project_registry, ...)`, the same resolver `lint_on_edit` uses (`handlers/pre_tool_use/staged_lint_gate.py:364`), and passes it in at line 396.
  - `lint_on_edit` calls it at `handlers/post_tool_use/lint_on_edit.py:450`.
  - I corrected the gate's comment, which made the false claim.
- **Other test changes:**
  - `tests/unit/strategies/lint/test_module_context_governing_config.py` (`TestWorkingDir`) now passes a `Workspace`.
- **Related, not fixed (out of scope):** the commit gate's `_resolve_executable` (`staged_lint_gate.py:444`) does not search the workspace's `bin_dirs`, but `lint_on_edit` does. In a sub-project whose linter lives in `frontend/node_modules/.bin`, the two gates can therefore still pick different linter binaries. This is worth a ledger entry.

## D2: dead production code

- **Real?** Yes. `git grep -w` across the whole tree (excluding the flagged fixture) finds no production caller of:

  - `write_marker`
  - `clear_marker`
  - `wrapper_execs_bare_script`

  The only other hits are `.claude/ccy/claude-supervise.py`'s unrelated `clear_marker` method, a docstring mention in `budget_exhaustion_detector.py`, plan documents, and tests.

- **Fix:**

  - Deleted `write_marker` and `clear_marker` from `src/claude_code_hooks_daemon/utils/blockage_marker.py`. I also dropped the `time` import, which became unused. I rewrote the module docstring: it described a writer and a clearer that no longer exist, and now says what is left (the legacy-import reader, `marker_is_valid`, `write_json_atomically`).
  - Deleted `wrapper_execs_bare_script` from `src/claude_code_hooks_daemon/utils/ccy_supervisor.py`. Its rationale moved into the docstring of `bare_script_lines` (line 131).
  - Removed the `clear_marker` entry from `scripts/qa/error_hiding_exclusions.json` (it was at line 591).
  - `budget_exhaustion_detector.py` about line 688: the docstring no longer names `write_marker`; it now cites the Plan 00314 contract directly.

- **Tests:**

  - `tests/unit/utils/test_blockage_marker.py` is rewritten. The `write_marker` and `clear_marker` tests are gone. The read tests now use a legacy-shaped marker. The owner-only, create-parents and overwrite properties are now asserted on `write_json_atomically`, plus a new test, `test_a_failed_write_raises`.
  - `tests/unit/utils/test_ccy_supervisor.py`: the three assertions now use `bare_script_lines`.
  - Three tests used `write_marker` only to put a legacy marker on disk. They now write it with `write_json_atomically` and the literal `{"session_id", "recorded_at"}` payload, which also pins the on-disk legacy format:
    - `tests/unit/core/test_data_layer.py`
    - `tests/unit/core/test_session_mode_registry.py`
    - `tests/unit/handlers/stop/test_idle_workable_issue_stop_gate.py`

## N3: the goal_loop_detector acceptance test passed whatever the handler did

- **Real?** Yes, though the expected decision itself was right. `handle()` always returns ALLOW (`handlers/stop/goal_loop_detector.py:200-262`). The problem was `requires_main_thread=False` on a `HandlerScope.MAIN` handler: run from a sub-agent, the handler never fires, so the ALLOW proved nothing.
- **Tests** (`tests/unit/handlers/stop/test_goal_loop_detector.py`):
  - `TestAcceptanceTests::test_every_case_runs_where_the_handler_fires` failed before the fix.
  - `TestAcceptanceTests::test_each_case_expects_what_the_handler_decides` feeds each case's `hook_input` to `handle()` and asserts the case's `expected_decision`.
- **Fix:** `requires_main_thread=True` (`handlers/stop/goal_loop_detector.py:461`).

## N5: session_mode_indicator crashed on a RuntimeError from the pause read

- **Real?** Yes. `_read_pause` calls `ProjectContext.daemon_untracked_dir()`, which raises `RuntimeError` when there is no context (`core/project_context.py:535-538`). Only `OSError` was caught, so `handle()` raised.
- **Test:** `tests/unit/handlers/status_line/test_session_mode_indicator.py::TestRender::test_a_pause_path_that_cannot_be_resolved_degrades_to_a_named_error`. It failed before the fix with the uncaught RuntimeError.
- **Fix:** `except (RuntimeError, OSError)` at `handlers/status_line/session_mode_indicator.py:146`. That path logs a WARNING and renders the named "usage-pause record unreadable" error. The `Raises:` section of `_read_pause` now documents the RuntimeError.

## Not changed (non-defects, per instruction)

- **N1:** `goal_loop_detector` imports private helpers from `auto_continue_stop`, and `usage_pause_gate` imports `daemon_is_unattended` from the `focus_mode_trigger` handler module. This is cross-handler coupling; moving the helpers to `utils/` is a refactor.
- **N2:** the removed options `marker_expiry_hours` and `expiry_hours` need a release-note or upgrade-guide check for client configs.
- **N4:** `relay_binary_checker` has a docstring/acceptance-test mismatch about resumes, and may compute the defect twice.
- **N6:** `RELEASE_STATE_FILENAME` is duplicated and should move to `constants/`.

## QA

- `./scripts/qa/run_autofix.sh` reported nothing to fix.
- `FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --range df6c44a3b..HEAD --allow-unmapped` on the fix commit:
  - Result: **`QA: 41/41 PASSED`**, no `❌` lines.
  - `changed_tests`: 4152 passed, 0 failed, 10 skipped.
- `lint_on_edit.py` and `staged_lint_gate.py` were reported unmapped (too broad), which leaves them to the full gate. I also ran their direct test files by hand: 513 passed, 5 skipped. Those files were:
  - `test_lint_on_edit*.py`
  - `test_staged_lint_gate*.py`
  - `test_ansible_governing_config_gates.py`
  - `test_unstattable_caller_paths.py`
  - `tests/unit/strategies/lint/`
