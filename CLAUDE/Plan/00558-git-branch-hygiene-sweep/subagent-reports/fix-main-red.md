# fix-main-red report (Plan 00558)

Branch `fix-main-red-558`, fix commit `d91fb7027` (from main 0c75cfa0b). Not pushed, not merged.

## Fixes

1. Example config (`.claude/hooks-daemon.yaml.example`, which is also the reference config): added `branch_creation_guard`, `branch_touch_recorder`, `evacuation_recorder`, `cleanup_after_merge`, `evacuation_turn_marker`, `branch_stop_guard`, `branch_subagent_stop_guard` with the live config's priorities. Covers failures 1 and 2.
2. Enumerated-content tripwire: the call at `core/branch_inventory.py` is `git diff --shortstat`, which prints totals only. `--shortstat` was added to the test's totals-only flags with a comment. The same test also flagged `core/branch_cleanup.py` (`git ls-files` followed by `read_text` of `.claude/hooks-daemon.env`). That was a real unprotected read, so `_is_generated_daemon_env` now consults `secret_file_matching.path_is_protected` and never reads a protected file (it stays a blocker).
3. Handler discovery: `BranchStopGuardBase` and `stop_guard_rule` moved to `handlers/utils/branch_stop_guard_base.py` (the utils dir is not scanned). Both concrete guards import from it. New test `tests/unit/handlers/utils/test_branch_stop_guard_base.py`; `tests/unit/handlers/stop/test_branch_stop_guard.py` patches the new module.
4. Priority band: added `branch_stop_guard` to the 0-9 row in `CLAUDE/HANDLER_DEVELOPMENT.md` and `docs/guides/CONFIGURATION.md`.
5. Evasion classification: `BranchCreationGuardHandler` is in `_EVASION_CASES` (git -C, --no-pager, env, line continuation, switch -c, git branch) and `_MUST_NOT_MATCH`; all pass.
6. Session-mode readers: declared `utils/branch_stop_guard_base.py` (stands aside while usage-paused) in `MODE_READERS`.
7. `tests/unit/core/test_branch_inventory.py`: five fake run_git defaults use `git_setup_timeout()`.
8. Bare wrapper strings: `SWEEP_CLEAN_COMMAND`, `SWEEP_COMMAND`, `DELETE_COMMAND` constants became functions (`sweep_clean_command`, `sweep_command`, `delete_command`) built with `daemon_cli_command_for_docs`, since the constant is context-dependent and must not be evaluated at import. The handler guidance strings use it too. Unit-test expectations updated.

## Verification

- All ten failing files plus `tests/daemon/test_server_response_schema.py`: 697 passed.
- Touched-module unit tests plus `tests/unit/install`: 3709 passed, 1 failed. The failure, `test_bin_wrapper_project_anchoring.py::test_a_global_anchor_selects_the_tree_the_command_reads`, is environmental: the worktree has no venv of its own, so `bin/hooks-daemon` finds none.
- ruff and black clean; mypy clean on the five touched source modules.
- The worktree has no venv, so tests ran with the main venv and `PYTHONPATH` set to the worktree `src`.

## Targeted QA

`llm_qa.py changed` did NOT run. It waited its full 5400 s for the host-wide QA lock, held by pid 1870236 in /workspace, and then refused to start. No QA verdict exists for this commit; the coordinator should run it (or the full gate) once the lock is free.
