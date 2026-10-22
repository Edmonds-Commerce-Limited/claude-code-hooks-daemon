# Plan 00546 Task 3.1: adviser rulings applied (Sonnet)

Branch `worktree-issue-130-p3-dbf`. `origin/main` merged (clean, no conflicts); release notes 016 and 017 untouched.

## Q1 (option A, conditions applied)

- `tests/unit/test_init_sh_snippets_parse_at_floor.py` (new): extracts each of the 10 `init.sh` allowlisted invoking lines' bodies (recovery source and
  suffixes, `$_recovery_py` spliced into the transport, shell variables and double-quote escapes resolved), asserts
  `ast.parse(..., feature_version=(3, 6))` and imports within `{json, os, shlex, socket, sys}`. A count test pins 10 extracted snippets against the
  allowlist, and a teeth test shows the walrus is rejected at the floor. 22 tests, all green on first run. Honest limit: it was green on
  first run because the adviser had already shown the snippets are clean, so its red is the teeth test, not a failing snippet.
  The 11th allowlisted line is `install.sh:123`, a validating bootstrap, not a snippet.
- `tests/old_python.py`: now provisions through `uv python install` when PATH and `uv python find` have nothing; skips only when `uv` is absent, with the
  reason naming that; a failed install raises `OldPythonProvisionError` and the test FAILS. `FORWARDER_PYTHON_FLOOR = (3, 6)` declared there.
  `uv` 0.13.5 is present on this host and provisioned 3.8 and 3.9: `test_python_floor.py` plus the hot-path old-Python integration test: 50 passed,
  0 skipped (before: 20 skipped). CI: `uv` availability in CI was not checked by me; if absent, the tests now say so in the skip reason.
- Tests of the provisioning helper: `tests/unit/test_old_python_provisioning.py`.
  Red before the change: `3 failed, 2 passed, 1 skipped`, e.g.
  `AttributeError: module 'tests.old_python' has no attribute 'OldPythonProvisionError'` and
  `Regex pattern did not match. Expected regex: 'uv is not installed' / Actual message: 'no Python 3.9 interpreter available'`.
- Allowlist description reworded: approved by delegated adviser; cites both gates. `OWNER-QUESTIONS.md` gains a Rulings section.

## Q2 (option B)

- CI out of scope: all 7 bare `python` lines follow `actions/setup-python` in their own job.
- `scripts/debug_info.py:18` verified: `from datetime import UTC` ran before any guard. Test first
  (`tests/unit/test_debug_info_old_python.py`, 3.8 and 3.9). Red output:
  `assert 'Traceback' not in 'Traceback (...tetime.py)\n'` ... `ImportError: cannot import name 'UTC' from 'datetime' (.../python3.8/datetime.py)`,
  and the same for 3.9, `2 failed`. Fix: `runpy` of `python_floor.py` before the imports (as `install.py` does). Green: debug_info tests + floor test
  `40 passed`.
- Follow-up plan scope (coordinator to file; I did not create it):
  1. Shebang detector for Python entry points a client may start with a bare `python3` (56 shebangs; 5 client-run candidates, of which `install.py`, `handler_status.py`,
     `error_response.py` and `audit_handler_config_keys.py` are already guarded by the package import or `install.py`'s own guard; `debug_info.py` fixed here). Decide the
     detector's universe first.
  2. Record the probe-result form as a known gap (0 instances: `bin/hooks-daemon:193` is floor-checked, `bootstrap-self-install.sh` is enforced by `uv` via
     `requires-python`, `claude-supervise` only reports). Build the rule when an instance appears.
  3. Optional: also guard the other client-run scripts uniformly once the detector exists.

## Q3 (option B)

Not built; recorded in `OWNER-QUESTIONS.md` as a known gap, 0 instances.

## Plan

Task 3.1 ticked, the QA-rule Success Criterion ticked. Status kept `In Progress`: flipping to Complete makes `plan_qa` demand the archive move
(`location-status-coherence`), which belongs with the merge. A new unticked Task 3.2 (merge, flip, archive) holds it so the body does not claim completion.

## QA

Whole-branch run over `origin/main..HEAD` (after the merge):
`QA: 37/41 PASSED, 2/41 FAILED, 2/41 NOT MEANINGFUL (detector failed: format, plan_qa)`.
`changed_tests`: 9066 passed, 0 failed, 36 skipped. The two failures:

- `format`: 3 files needed Black reformatting (`scripts/debug_info.py`, `tests/unit/test_old_python_provisioning.py`, and
  `scripts/qa/check_bare_python_invocation.py`, which was already unformatted on this branch). The run's own autofix rewrote them; committed.
- `plan_qa` `header-body-coherence`: from my first tick of Task 3.1 (header In Progress, body complete); resolved by Task 3.2 above.

Re-run of `format plan_qa docs_qa repo_hygiene` on the final tree: `QA: 4/4 PASSED`. The skipped 36 tests are not from the old-Python files.

## Head commit

See the reply; it is the commit of this report.
