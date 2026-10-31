# DBF full-gate failures: fixes

1. test_debug_hooks_socket_discovery: the test sliced the script up to the old `if [[ ! -f "$VENV_PYTHON"` line, which ed51d5951 replaced with `if ! venv_python_usable "$VENV_PYTHON"`. The end marker now matches the new line. No production change.
2. test_ci_passthrough TestNonCIDaemonFailure: `_create_installed_stub` wrote a bash script that exits 1. That is the hazard the gate refuses (existing and executable, yet not a usable interpreter), so `_is_daemon_installed` now returned false and the "Not installed" path ran. The fixture is now a layout `nonexistent/bin/python` that symlinks `os.path.realpath(sys.executable)`, with a `nonexistent/pyvenv.cfg` recording the running major.minor, plus a symlink of `scripts/lib` into the fake install so the gate library can be sourced (a real install ships it). The template PYTHON_CMD points at the new path. Production `init.sh` is unchanged.
3. check_python_var_guidance: UntrustedVenvInterpreter.md lines 94, 96, 183 spelled the literal `$PYTHON`. Reworded to describe the resolved interpreter and the `-x` / `-f` tests without the variable.
4. release_gate_layout: added `venv_interpreter_trust` to CHECKS_STATIC in `.github/workflows/release-gate.yml`.

Verification: the five test files pass (183). The full-QA lock blocked `llm_qa.py venv_interpreter_trust`, so `scripts/qa/check_venv_interpreter_trust.py` was run directly: rc 0, no findings. Black and ruff are clean on the changed Python files.
