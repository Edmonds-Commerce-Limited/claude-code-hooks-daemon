# DBF fix, phase 1: the SSoT gates and the core files

Branch `p555-dbf-fix`. Detector: 62 findings before; in the scoped files 3 remain, all listed as owner items below.

## Gates

- Python: `venv_interpreter_usable(python_path) -> bool` in `daemon/paths.py` replaces `_venv_interpreter_runs`. It runs the probe, then compares the `pyvenv.cfg` major.minor with the running one, so its own body proves the rule. "Cannot tell" (no cfg or version, a probe that prints none) passes.
- Bash: `venv_python_usable <python_path>` in `scripts/lib/resolve_venv.sh`. Contract in the header: one argument, returns 0 or 1, never prints, reason in `_RV_PROBE_OUTPUT`. `_rv_candidate_runs` is now probe only (it leaves the version in `_RV_PROBE_VERSION`) and `_rv_check_cfg_drift` is gone, folded into the gate.
- `GATES` in the detector now names both (plus `_rv_cached_venv_current`). Detector confirms both are proven.

## Findings fixed (by file)

- `resolve_venv.sh`: the scan, the `HOOKS_DAEMON_VENV_PATH` override (it used to be returned on `-x` alone) and `resolve_venv_python_in_venv` all go through the gate. A drifted override now falls through, matching the Python resolver.
- `paths.py`:
  - `resolve_existing_venv_python` (keyed branch) and `_best_ranked_scan_candidate` use the gate. The scan ranks first and probes in rank order until one passes. The "deliberately no probe" docstring is replaced: shell callers (`health_check.sh`, `upgrade_version.sh`, `qa/run_all.sh`) execute the result.
  - `venv_interpreter_drift` drops its exec-bit pre-check.
  - `live_venv_realpaths` asks the gate instead of `.exists()`.
- `bin/hooks-daemon` and the template: the last gate before exec is `venv_python_usable`. The two files are identical in the changed region.
- `init.sh`: `_is_daemon_installed` asks the gate and sources the library if `PYTHON_CMD` was preset.

## Non-lexical causes

- (d) `_cli_check_venv_fresh` returns STALE when an interpreter in `bin/` fails the gate, whatever the lock_hash says.
- (e) With the version-aware resolver a drifted venv leaves `PYTHON_CMD` empty, so `_is_daemon_installed` is false and `ensure_daemon` reaches VENV_MISSING and `_venv_self_heal`. The `bin/hooks-daemon` repair arm is gated on "nothing resolves" and so fires too. Tests: `TestInitShTreatsADriftedVenvAsNotInstalled`, `TestOverrideIsGated`. I did not run `ensure_daemon` end to end through the sandbox; the chain is shown per step.
- (f) `_vb_build_under_lock` judges success by `resolve_venv_python`, which is now version-safe. Test: `TestBuildSuccessIsJudgedByTheVersionAwareResolver`.
- `_repair_venv_locked`: new `fingerprint_major_minor()` in `paths.py`. It fails the repair when `uv sync` built a different minor than the fingerprint tag, and when the built interpreter fails the gate.
- `_write_venv_metadata` (`cli.py`, was flagged `:3899`) now refuses to stamp a venv whose `bin/python` fails the gate. This is a real fix: a drifted venv could be stamped fresh.

## Tests

- New: `tests/unit/daemon/test_paths_venv_gate_consumers.py` (14) and `tests/integration/test_dbf_gate_shell_consumers.py` (9).
- Renamed or updated: the two drift tests, the detector GATES test, and `test_init_sh_pretooluse_fail_closed.py` (its fixture presets `PYTHON_CMD`, so it now sources the library).
- Passing: 530 unit and integration tests around paths/cli/venv, and 600 shell integration tests (`test_init_sh_*`, `test_resolve_venv_*`, bootstrap, bin wrapper). ruff, black, mypy and shellcheck are clean.
- I wrote the code before the tests, not test first. I did not run the new tests against the pre-change code to see them fail.

## Owner items (still flagged, no exemption added)

1. `cli.py:3339` and `:3341` (`list-venvs` recognising a venv dir by `bin/python`). Recognising it by `pyvenv.cfg` is the honest improvement; I tried it and reverted. 23 existing fixtures in `test_cli_venv_management`, `test_cli_current_venv_agreement`, `test_cli_live_venv_guard_real_layout` and `test_cli_venv_symlink_accounting` build fake venvs with a `bin/python` and no `pyvenv.cfg`. Needs a follow-up that adds a cfg to those fixtures, then the one-line change.
2. `paths.py:418` (`_probe_python_version`, `--version` on a PATH-discovered system interpreter). It selects a base interpreter to build a venv with and never reads a venv. Switching to `-c` would only change which detector shape matches, not the hazard, so I left it.

## Not done

- `CLAUDE/Security/UntrustedVenvInterpreter.md` still names the old gate names; the doc needs updating.
- Remaining shell scripts (skills scripts, `venv-include.bash`, `install.sh`, etc.) are for the later agent.
