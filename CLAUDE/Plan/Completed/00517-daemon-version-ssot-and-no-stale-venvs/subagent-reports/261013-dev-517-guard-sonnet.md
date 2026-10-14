# Plan 00517 Task 3.0 (N456): live-venv guard identifies the venv by directory

## Defect

`_resolver_active_venv_realpath` (daemon/cli.py) returned `python_path.resolve().parent.parent`. A real venv's `bin/python` is a symlink to the system interpreter, so this yielded `/usr`, never the venv. The running venv was therefore selectable by `prune-venvs --all-except-current` when its fingerprint differed from the current one.

## Fix

`_live_venv_realpaths(project_root) -> frozenset[Path]` replaces it. Live venvs are `Path(sys.prefix).resolve()` plus the resolver's python path taken as `.parent.parent` on the UNRESOLVED path and only then resolved (which still follows a symlinked venv directory). Callers (all found by grep): `_enumerate_venvs` (feeds `is_current`, hence `_reclaimable_venv_entries`, `disk-usage`, `list-venvs`) and `cmd_prune_venvs`' skip. `paths.py list-stale-venvs` compares resolved directories already and has no such flaw.

## TDD

`tests/unit/daemon/test_cli_live_venv_guard_real_layout.py` (7 tests) builds venvs in tmp_path whose `bin/python` symlinks to `Path(sys.executable).resolve()` with a non-current fingerprint. Red first: 5 of 7 failed, including `--force` deleting the live venv inside the tmp dir. Green after the fix; the Plan 00184 accounting tests still pass (13 passed together). No real directory was pruned.

## Other changes

Release note 052; PLAN.md Task 3.0 ticked; plan status flipped Not Started to In Progress (plan_qa header-body-coherence blocked otherwise) with the README row; journal entry via `mkplan.bash --journal 517 action` (`progress` is not a valid category: action finding decision thought blocker handoff correction).

## QA

`llm_qa.py changed`: 39/40 PASSED, 1 FAILED. The one failure is changed_tests reporting `src/claude_code_hooks_daemon/daemon/cli.py [too-broad]` as unmapped (2596 tests passed, 0 failed). It is pre-existing and independent of this change: cli.py reaches more than MAX_IMPORT_SELECTION (40) test files, and a `changed_tests_map.yaml` glob rule for cli.py did not clear it (tried and reverted). Any cli.py edit needs `--allow-unmapped` or the coordinator's full gate.
