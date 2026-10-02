# N285: upgrade-approval env-bypass rule scope

**Branch**: worktree-n285-env-bypass-scope

## Root cause

In `upgrade_approval_guard.py`, `_segment_runs_upgrade` sent every segment whose head word began with `$` (`$PY/python`, `$P`) to `_script_run_is_upgrade`. That cannot read a `$`-path, so it answered "cannot tell", and once `PYTHONPATH` (matched by `PYTHON*`) steered the command, "cannot tell" counted as the upgrade. The arguments were never looked at.

## Fix

New `_variable_program_is_upgrade` judges a variable program by its arguments:

- literal `-m <module>` outside the `claude_code_hooks_daemon` package: not an upgrade
- literal script path: read and judged by content (handoff signature), like any other script
- `-c`, `-`, `--`, no operand, computed (`$`/backtick) module or script, unreadable or missing script, `-m claude_code_hooks_daemon...`: "cannot tell", denied when steered

Entry-point names (`upgrade.sh`, `upgrade_version.sh`, `upgrade_gate_standalone.py`), `--skip-reading-confirmation`, `--uv`, and the handoff-variable assignment are caught before or independently of this path and are unchanged.

## Allowed now

- `PY=/x/venv/bin; PYTHONPATH=$PWD/src $PY/python -m pytest -q tests/unit/foo.py`
- `P=...; PYTHONPATH=$PWD/src $P scripts/qa/audit_error_hiding.py` when the script resolves (hook input carries `cwd`) and is not the upgrade

## Still denied (tests added)

`$P "$SCRIPT"`, `$P $SCRIPT`, `$PY -c ...`, `$PY -m "$MOD"`, bare `$PY`, `$PY -`, `bash -c "$X"`, a missing script, `$PY -m claude_code_hooks_daemon.daemon.cli upgrade`, `bash .claude/hooks-daemon/scripts/upgrade.sh`, `$PY scripts/upgrade.sh`, `$PY --uv /tmp/uv scripts/upgrade.sh`, a script carrying the handoff variable, and any `HOOKS_DAEMON_UPGRADE_HANDOFF=` assignment.

## RED / GREEN

- RED: `-k VariableInterpreter` gave 6 failed, 18 passed. Five were the allow cases; the sixth was `PYTHONPATH=x eval "$X"`, which is already allowed before this change, so I removed it from the deny list (see not verified).
- GREEN: whole `test_upgrade_approval_guard.py`, 217 passed.
- Worktree copy imported: `PYTHONPATH=$PWD/src <venv>/bin/python -c ...` printed `/workspace/untracked/worktrees/worktree-n285-env-bypass-scope/src/claude_code_hooks_daemon/__init__.py`. The pytest runs used `-o pythonpath="src ."` from the worktree.

## QA

ruff, black --target-version py311, mypy, pyright on the handler (and ruff/black on the test): clean. `scripts/qa/audit_error_hiding.py`: exit 0. `scripts/qa/check_input_contract.py`: exit 0. `scripts/qa/llm_qa.py changed`: 28/28 passed (273 changed-tests passed, 5 skipped). It noted the tree changed during the run (the report was written meanwhile), so the result is not recorded for the tree.

## Not verified

- `PYTHONPATH=x eval "$X"` stays allowed (pre-existing: eval is only suspect beside a command that runs the upgrade). Denying it would also deny `export PYTHONPATH=x; eval "$(ssh-agent)"`. Say so if you want it widened.
- A literal interpreter running `-m claude_code_hooks_daemon... upgrade` is still allowed (pre-existing; the literal path is judged by the binary's content). Only the variable-interpreter form is denied. Whether the daemon CLI has an `upgrade` subcommand was not checked.
- The `$P scripts/qa/...` allow needs the hook input `cwd`; with no `cwd` a relative script is "cannot tell" and denied.
- No full suite, no real upgrade, no daemon restart.
