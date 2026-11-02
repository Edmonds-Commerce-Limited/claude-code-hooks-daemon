# DBF fix, final: detector reports zero findings

Branch `p555-dbf-fix`. Detector: 16 findings at the start, 0 now ("No venv interpreter trusted without a version check (1024 files)"). Every item was fixed; none is left as an owner item.

## Per item (each test run red first, then green)

1. `scripts/upgrade.sh` metadata block (`dc650805b`): sources `resolve_venv.sh` non-fatally (daemon dir, else beside the script); takes the first `venv-*py3*` glob hit that passes `venv_python_usable`; with no gate available it records nothing. Seven repeated `[ -x ]` guards reduced to `[ -n ]`. Test: `tests/integration/test_dbf_upgrade_metadata_gate.py` (6; 5 were red).
2. `upgrade.sh:967` (`0298f52c5`): detector bug fixed, variable not renamed. A `local`/`declare`/`typeset` in a function shadows the outer interpreter binding; a local the function itself binds to an interpreter, and an unshadowed use, are still reported. Fixture tests in `tests/unit/qa/test_check_venv_interpreter_trust.py` (`TestShellLocalShadowing`, 7 tests, 5 red).
3. `upgrade.sh:345` (`dc650805b`): the discovery library does not expose the version it found, but its helper `_pd_probe_version` parses it, so the message uses that. No `--version` run inline. The detector narrowing was not built (reason in the Security doc).
4. `rollback.sh` (`e0515c094`): a usable venv records the interpreter version and takes the `pip freeze`; a drifted one is recorded from `pyvenv.cfg` as `3.11.2 (interpreter drifted)` and its pip is skipped. `python_version` has no reader other than the manifest. Test: `tests/integration/test_dbf_rollback_snapshot_gate.py` (3).
5. Both historical `verification.sh` (`d262dd275`): inline awk + `sys.version_info` compare of pyvenv.cfg, no library sourced; the detector accepts it.
6. `paths.py _probe_python_version` (`780babfad`): returns None for a venv interpreter (`pyvenv.cfg` two levels up) that `venv_interpreter_usable` refuses. 3 tests in `tests/unit/daemon/test_paths_python_discovery.py`.
7. `CLAUDE/Security/UntrustedVenvInterpreter.md`: Fix column filled for every row; local-shadow rule recorded; the no-hazard list replaced by a resolved list.

## Checks

shellcheck `-S warning`, ruff, black and mypy clean on the changed files. 191 tests pass (detector, paths discovery, the two new files, the previous gate-script tests); 82 existing `test_upgrade_sh_*` and neighbouring upgrade tests pass. Run with `untracked/venv-wt/bin/python -m pytest ... --no-cov`.

## Notes for the coordinator

- Pre-existing, not touched: `create_state_snapshot` never creates `files/venv/` or `files/gitignore/`, so its pip-freeze and gitignore backups silently fail on a real run. The new test pre-creates the directory to prove the gate. Worth a niggle.
- `verification.sh` (v2.0-to-v2.1) has an old shellcheck info (SC2086, line 163) on code I did not change.
