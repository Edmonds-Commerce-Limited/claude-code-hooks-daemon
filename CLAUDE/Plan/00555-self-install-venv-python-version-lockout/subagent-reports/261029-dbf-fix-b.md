# DBF fix, phase 1b: red proof, the owner-listed findings, the doc

Branch `p555-dbf-fix-b` (from `p555-dbf-fix` at `b51912cb8`).

## 1. The previous phase's tests against the pre-fix tip (`6edb526c7`)

Run in a temporary detached worktree (removed afterwards) with the five new or updated test files copied in from `b51912cb8`. The two symbols that did not exist yet (`fingerprint_major_minor`, `venv_interpreter_usable`) were stubbed to raise, so each test is judged on its own and the module does not die at import.

Red (they reproduce the defect or need the new symbol):

- `test_paths_venv_gate_consumers.py`: 11 of 14 fail. Behavioural reds: drifted venv judged fresh despite matching lock; drifted venv stamped by `_write_venv_metadata`; drifted keyed venv returned first; drifted venv counted live; `repair` returned 0 for a different minor. The 5 `fingerprint_major_minor` cases and the gate test need the symbol.
- `test_dbf_gate_shell_consumers.py`: 5 fail. Real behavioural reds: drifted `HOOKS_DAEMON_VENV_PATH` still resolved, `resolve_venv_python_in_venv` accepted a drifted venv, `init.sh` called a drifted venv INSTALLED. Two `TestTheBashGateNeverPrints` cases fail only because `venv_python_usable` does not exist.
- `test_resolve_venv_interpreter_drift.py` (5) and `test_paths_venv_interpreter_drift.py` (5): fail on the renamed gates, same as before the rename.

Green on the old code (honest findings):

- `TestBuildSuccessIsJudgedByTheVersionAwareResolver` (both tests) passes on the old code. The Python resolver that `resolve_venv_python` finally runs already refused drift (Task 2.2), so cause (f) was not a live defect at `6edb526c7`. I could not make it red without inventing a defect; it is a regression guard and the doc now says so.
- The control cases (matching interpreter is fresh, stamped, repaired, resolves) pass, as they should.
- One test was red for the wrong reason: `test_refuses_a_drifted_venv` used an invalid version `v1`, so the old code failed on schema validation, not on drift. Fixed to `v1.2.3`; it now fails on the old code with `assert None is not None` (it stamped the drifted venv).

## 2. Owner items

- `cli.py` venv listing: a directory is now a venv when it has `pyvenv.cfg`, not when it has `bin/python`. Changed `_enumerate_venvs`. The fixtures that faked venvs now write a `pyvenv.cfg` (the real-interpreter ones record the running `version_info`): `test_cli_venv_management.py`, `test_cli_current_venv_agreement.py`, `test_cli_live_venv_guard_real_layout.py`, `test_cli_venv_symlink_accounting.py`, plus two the previous agent did not list, `test_cli_disk_usage.py` and `test_cli_stale_venv_cleanup_on_start.py`. There was no shared helper (each file has its own `_make_venv`), so each got one line. The "skips venv without python binary" test became `test_enumerate_skips_directory_without_pyvenv_cfg` and asserts that an impostor with `bin/python` and no cfg is not listed (it fails on the old logic).
- `paths.py:418` `_probe_python_version`: LEFT FLAGGED. No lexical criterion separates it from a venv interpreter: the function takes any `Path`, and an activated venv puts its own `bin/` on `PATH`, so PATH discovery can reach one. The only distinguishing facts are the function's name and its callers, which would be an exemption by another spelling. No detector change. For the owner: the probe parses a version to pick a base interpreter, so the practical hazard is small; accepting it needs a deliberate decision.

Detector now: 1 Python finding (`paths.py:418`); the rest are shell scripts for the other agent.

## 3. Doc

`CLAUDE/Security/UntrustedVenvInterpreter.md`: names `venv_interpreter_usable` and `venv_python_usable`; the core rows' Fix column is `b51912cb8`; the cli.py entries are gone from the no-hazard list; `_probe_python_version` is explained; (d), (e), (f) are marked as fixed by hand in `b51912cb8` (with (f) described as a regression guard).

## QA

ruff, black, mypy clean on the changed Python. 207 targeted tests pass. `tests/unit/daemon/test_cli_cmd_start.py` has 4 failures (BrokenPipeError) that also occur in the `p555-dbf-fix` worktree, so they are not from this change.
