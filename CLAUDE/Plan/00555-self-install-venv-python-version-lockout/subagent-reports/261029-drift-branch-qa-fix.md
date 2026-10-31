# Drift branch QA fix (Plan 00555)

Branch agent-af24d7290dc06defe-50178723. Source fixes are commit 63703130d.

## Fixes

1. magic_values: `tests/integration/test_resolve_venv_interpreter_drift.py` lines
   49, 80, 111 (after the Black re-wrap) and 145. The bare `timeout=30` and
   `timeout=60` are now `Timeout.REQUEST_DEFAULT` and `Timeout.REQUEST_LONG`,
   imported from `claude_code_hooks_daemon.constants` at line 19, as the other
   integration tests do. Rerun: 0 violations.

2. error_hiding, `src/claude_code_hooks_daemon/daemon/paths.py`:

   - `venv_cfg_major_minor` (line 987 on): the try/except is gone. An explicit
     precondition (`cfg.is_file()` and `os.access(cfg, os.R_OK)`) returns None
     for the ordinary "no record" case; nothing is swallowed.
   - `venv_interpreter_drift` (line 1027 on): the probe moved to a new helper
     `_probe_version_stdout` that returns `""` when the interpreter cannot be
     asked, and the loop tries the next name on an empty answer. No
     except-continue remains.
   - First attempt, rejected: the sanctioned `log_and_continue` helper. It
     passed error_hiding but broke 10 tests in
     `test_init_sh_venv_self_heal.py` and `test_skill_install_never_auto_forces.py`.
     `paths.py` runs standalone by file path during bootstrap, and the helper
     lazy-loads `utils/escape_hatch.py` from the package directory, which is
     absent in those sandboxes (FileNotFoundError). Any exception-handling
     logging helper in this file's bootstrap-reachable functions has that risk.
     Rerun: error_hiding, magic_values, format, lint, type_check and pyright
     all 0 violations.

3. changed_tests: not fixable by a map rule, so no map change was made.
   `run_changed_tests.py::cover` sets the `too-broad` reason regardless of
   declared rules (a rule adds tests, it never clears the reason). Both files
   are too broad by reach:

   - `src/claude_code_hooks_daemon/daemon/paths.py`: its own tests are 90 files
     (cap 40).
   - `scripts/lib/resolve_venv.sh`: 46 test files through the dependent
     `scripts/qa/llm_qa.py`.
     CLAUDE/QA.md ("The Unmapped and Too-Broad Fallback", and "A `too-broad` file
     is beyond what mapped tests can certify, so `--allow-unmapped` is its honest
     answer") names `--allow-unmapped` as the answer, with the whole-suite run
     (CI's `full_suite_if_unmapped.bash` or the release Full tier) as the
     certifier. Nothing was weakened. The handover must state that these two
     files are not locally certified beyond the explicit pytest set below.

4. Failing advisor test: the fixture was wrong, production is right.
   `tests/unit/handlers/session_start/test_unproven_venv_advisor.py` wrote
   `version = 3.11.2` into a venv whose `bin/python` is the running
   interpreter (3.13), which is genuine drift, so the new rule correctly
   classifies it STALE. The fixture now records the running interpreter's
   major.minor (`_CFG_VERSION`, defined after `STALE_HASH`, used in `_venv`).
   This mirrors the fix the branch already made in
   `tests/unit/daemon/test_cli_unproven_venvs.py`. Intent of the test is
   unchanged; no production behaviour changed.

## Verification

- Pytest, the two drift files, the advisor test and `test_cli_unproven_venvs.py`:
  44 passed. Run with the worktree's own venv
  (`untracked/venv-workspace_claude_worktrees_agent-af2-a32a-py313-0d6d49c6`),
  not `/workspace`'s venv: with the latter `tests/conftest.py` raises
  `SourceTreeMismatch` (the editable install points at main's src/), so it
  cannot test the worktree's sources.
- `llm_qa.py magic_values error_hiding format lint type_check pyright`: all pass.
- `changed_tests --allow-unmapped`: see the final reply for the result.
