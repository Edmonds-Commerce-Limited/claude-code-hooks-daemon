# DBF fix, phase 2: the shell scripts (PARTIAL, handed off at the context budget)

Branch `p555-dbf-fix`. Detector: 46 findings at the start of this phase, 18 now. Of the 46, 42 were in my scope (cli.py x2 and paths.py x1 belong to others, plus the 3 carried owner items).

## Done (each with a test run red first, then green)

Tests: `tests/integration/test_dbf_gate_shell_scripts.py` (24 tests). Run with `untracked/venv-wt/bin/python -m pytest <file> -q -p no:cacheprovider --no-cov` (the worktree's own venv; main's venv trips `source_tree_guard`).

- Skill wrappers `{daemon-cli,health-check,init-handlers}.sh`, both the `.claude/skills/...` copy and the `src/.../skills/...` source: `[ ! -f "$PYTHON" ]` is now `! venv_python_usable "$PYTHON"`. All three already `source "$RESOLVE_LIB"`, so no new sourcing and the `_resolve-venv.sh` shim is untouched. The pairs are byte-identical (`diff -r` clean); `test_deployed_skill_trees.py` and `test_skill_scripts_venv_resolution.py` pass.
- `debug_hooks.sh`, `qa/run_canonical_callers_check.sh`, `qa/run_strategy_pattern_check.sh`: gate (they get it via `venv_resolver.sh` / `resolve_venv.sh`, which they already source).
- `upgrade_version.sh`: all six `-f "$VENV_PYTHON"` sites (five code, one comment). Tested statically only (the script needs git, uv and a network to run); 60 neighbouring upgrade tests pass.
- `install/venv.sh`: new `_venv_load_gate` (lazy-sources `scripts/lib/resolve_venv.sh` from its own location, fails closed). `verify_venv` uses the gate instead of exists/executable/`--version`. `venv_lock_hash_matches` lost its `[ -x ]` fallback: no gated interpreter now means "rebuild". `install_package_editable` and `eager_cleanup_stale_venvs` use the gate (the skip warning now carries the gate's reason). `get_venv_python_version` had no caller anywhere, so it was deleted (and its README row).
- `install_version.sh` (now sources `venv_resolver.sh`), `setup_worktree.sh`, `validate_worktrees.sh`: gate. `venv-include.bash`: `venv_exists`, `venv_tool` (gates the interpreter first) and the post-creation check at about line 157 (honest improvement, not left flagged).
- shellcheck `-x -S warning` clean on every changed script. Neighbouring suites pass (ensure_venv\*, verify_venv, eager cleanup, venv-include, install resolver, 86+ tests).

## Remaining (not done) and the plan for each

1. `scripts/upgrade.sh` 923, 932, 998, 1052, 1106, 1158, 1253, 1289. The tail metadata block picks the first executable of `untracked/venv-*py3*/bin/python` and writes it to metadata. It carries a `canonical-resolver-exempt` comment: it must stay dependency-light and non-fatal. Plan: try `source "$DAEMON_DIR/scripts/lib/resolve_venv.sh"` (non-fatal); if `venv_python_usable` is then defined, take the first glob hit that passes it (not the first executable); otherwise leave `_metadata_venv_python` empty (fail closed; the metadata fields are already allowed to be empty). Then replace the seven repeated `[ -n "$x" ] && [ -x "$x" ]` guards with `[ -n "$x" ]` (only gated values are ever assigned). Update the stale comment. Test: run the metadata block against a fixture DAEMON_DIR with a drifted `venv-x-py3-y` (see `test_upgrade_metadata_emission.py` for the harness) and assert empty `python_path`.
2. `scripts/upgrade.sh:967` is a false positive the detector missed in the report: `_find_new_config_backup` loops over config backups with a variable called `_candidate`. Rename the variable to `_backup`; no behaviour change.
3. `scripts/upgrade.sh:345` (FP): `--version` printed in a message for the interpreter `find_latest_python` already version-checked. Leave flagged and list for the owner, or print the version through `-c` (that only changes which pattern matches; I would leave it).
4. `scripts/install/rollback.sh` 132, 133, 210 (FP): reporting and a best-effort `pip freeze` backup. Routing 132/133 through the gate would lose the `python_version` field of a rollback manifest for a drifted venv, which is the record you want most. Recommend leaving flagged and listing for the owner. 210 may take the gate if the backup is skipped with a loud message; check `test_*rollback*` first.
5. `CLAUDE/UPGRADES/v2/v2.0-to-v2.1/verification.sh:79` and `v2.12-to-v2.13/verification.sh:26`: inline a pyvenv.cfg major.minor compare against the interpreter's own `sys.version_info` (no library sourcing). The cfg is `version_info = M.m.p` or `version = M.m.p`.

## Owner items so far (still flagged, no exemption)

- `cli.py:3339`, `:3341`, `paths.py:418`: carried from phase 1, not in my scope.
- `setup_worktree.sh:307`: the detector report asked whether the later `-py{MM}-` tag compare counts as proof. I routed the check through the gate instead, so the question is moot; the tag compare stays as an additional check.

## Not done

- Final detector run reporting zero in scope, and the final commit of items 1 to 5.
