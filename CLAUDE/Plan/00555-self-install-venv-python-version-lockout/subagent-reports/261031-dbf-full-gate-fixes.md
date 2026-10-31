# DBF full-gate failures: fixes

1. test_debug_hooks_socket_discovery: the test sliced the script up to the old `if [[ ! -f "$VENV_PYTHON"` line, which ed51d5951 replaced with `if ! venv_python_usable "$VENV_PYTHON"`. The end marker now matches the new line. No production change.
2. test_ci_passthrough TestNonCIDaemonFailure: `_create_installed_stub` wrote a bash script that exits 1. That is the hazard the gate refuses (existing and executable, yet not a usable interpreter), so `_is_daemon_installed` now returned false and the "Not installed" path ran. The fixture is now a layout `nonexistent/bin/python` that symlinks `os.path.realpath(sys.executable)`, with a `nonexistent/pyvenv.cfg` recording the running major.minor, plus a symlink of `scripts/lib` into the fake install so the gate library can be sourced (a real install ships it). The template PYTHON_CMD points at the new path. Production `init.sh` is unchanged.
3. check_python_var_guidance: UntrustedVenvInterpreter.md lines 94, 96, 183 spelled the literal `$PYTHON`. Reworded to describe the resolved interpreter and the `-x` / `-f` tests without the variable.
4. release_gate_layout: added `venv_interpreter_trust` to CHECKS_STATIC in `.github/workflows/release-gate.yml`.

Verification: the five test files pass (183). The full-QA lock blocked `llm_qa.py venv_interpreter_trust`, so `scripts/qa/check_venv_interpreter_trust.py` was run directly: rc 0, no findings. Black and ruff are clean on the changed Python files.

## Second round: symlinked-project wrapper stub and git-enumerated content

- tests/integration/test_a_daemon_of_a_symlinked_project_is_stoppable.py: its stub
  resolve_venv.sh defined only `resolve_venv_python`, so the wrapper's
  `venv_python_usable` call (line ~281) failed. The stub now sources the real
  scripts/lib/resolve_venv.sh (real gate) and then pins the interpreter.
- scripts/qa/check_venv_interpreter_trust.py: `scanned_files` enumerated with
  `git ls-files` and delegated protected-path filtering to a sibling module, so the
  Plan 00412 class 9 tripwire saw no protected-set check in this module. Added a local
  `_without_protected` (unguarded import of `path_is_protected` /
  `resolve_configured_patterns`), mirroring check_sensitive_content.py.
- Other `resolve_venv_python()` stubs in tests/ (test_dbf_gate_shell_scripts.py,
  test_init_sh_resolve_python_cmd_status.py, test_venv_bootstrap_hostile_path_epoch.py,
  test_worktree_socket_path_preflight.py) either source the real gate or return 1 and
  never reach it; all pass unchanged. No further fixes needed.
- Detector exits 0; black and ruff clean.
