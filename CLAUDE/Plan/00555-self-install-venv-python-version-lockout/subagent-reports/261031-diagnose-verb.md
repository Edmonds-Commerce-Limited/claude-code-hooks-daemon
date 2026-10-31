# Task 2.5 (decision-neutral half): `hooks-daemon diagnose`

## What was found

The Python CLI (`daemon/cli.py`) has no `diagnose` verb, only `paths.py diagnose-venv`. The wrapper arm is therefore the single entry point.

## What changed

- `bin/hooks-daemon` and its byte-identical template `src/claude_code_hooks_daemon/install/templates/hooks-daemon`:
  - new `diagnose` arm in `_run_venv_free_verb`, calling `_diagnose_venv_free`;
  - an early call before `resolve_venv_python`, so it also runs when a venv resolves (a healthy venv must exit 0);
  - design note 4 updated.
- `tests/integration/test_bin_hooks_daemon_diagnose_without_venv.py`: 7 tests (drifted, healthy, no venv, build record, live pid read-only, global option, wrapper/template identity).

## Behaviour

- Runs `paths.py diagnose-venv --daemon-dir D --venv-dir V` for every `untracked/venv-*`, under that venv's own `bin/python` with `timeout`. No bare PATH python3.
- A venv whose diagnosis cannot run (exit other than 0/1) is named. If no venv exists it prints "no venv found".
- Prints the last build (`untracked/.venv-bootstrap.result`) via `_print_last_build 2>&1`, and `daemon: running (pid N)` or `not running` (CLAUDE_HOOKS_PID_PATH, else `untracked/daemon*.pid`, `kill -0`), plus the socket when CLAUDE_HOOKS_SOCKET_PATH is set. Read-only.
- Exit 0 iff at least one venv is healthy (a dangling other-environment venv does not fail it). Otherwise it prints `fix: <bin>/hooks-daemon repair` and exits 1.
- Not touched: any allow-list or hook-side guard.

## Notes

- Tests were written alongside the implementation, so there was no separate red run.
- `venv_interpreter_trust` flagged an `-x` test on the first draft; removed, and a failed exec now shows as "could not run the diagnosis (exit N)".

## QA result lines (verbatim)

First targeted run: `QA: 8/9 PASSED, 1/9 FAILED` (venv_interpreter_trust, then fixed).
After the fix: `QA: 3/3 PASSED` for venv_interpreter_trust, shell_check and bare_python_invocation. The other six passed in the first run (lint, type_check, format, pyright, error_hiding, semgrep).
Tests: `7 passed` (new file), `26 passed` (with the repair-without-venv file).

`llm_qa.py changed`: `QA: 39/42 PASSED, 2/42 FAILED, 1/42 NOT MEANINGFUL (detector failed: plan_qa)`. The two failures are not from this change:

- `plan_qa`: 0 block, 1 advise (journal-freshness on 00554-rust-relay-transport-default, 4 days quiet).
- `changed_tests`: 218 passed, 0 failed. The only failure cause is `unmapped ... bin/hooks-daemon [too-broad]`. This is a changed_tests_map gap that any wrapper edit hits. It is a coordinator or map decision, not fixed here.

An earlier `changed` run showed 1 failed test (`test_bin_wrapper_project_anchoring`) only because the worktree had no `untracked/venv-*`; after symlinking `.venv` as `untracked/venv-worktree-local` it passes (gitignored, not committed).
