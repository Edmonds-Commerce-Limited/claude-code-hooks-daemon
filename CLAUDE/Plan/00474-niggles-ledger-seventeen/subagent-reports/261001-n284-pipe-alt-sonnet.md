# N284: pipe blocker read `\|` and an uppercase `HEAD` as a pipe

Branch `worktree-n284-pipe-quoted-alt`.

## Root cause

`PipeBlockerHandler._pipe_pattern` is a regex over the raw command, compiled
`re.IGNORECASE`, with no notion of a backslash-escaped bar. In
`grep -rn "HEAD:x\|rev:path\|..." ... | cut` it matched `|HEAD` inside the
double quotes. Producer extraction then returned the text before that bar (the
quoted pattern), so the deny named it. The segmenter was correct.

## Fix

- pattern is case-sensitive
- `_pipe_matches` skips a bar preceded by an odd run of backslashes (literal in
  double quotes and unquoted); an even run (`\\|`) stays a real pipe
- both `_find_offending_match` and `_extract_source_segment` use it
- two old tests asserting `| TAIL` / `| Head` are blocked were inverted

Unchanged on purpose: a bare `| head` inside plain quotes is still judged, per
the existing documented posture.

## Evidence

Runner `untracked/scratch/run_tests.py` inserts the worktree `src` at
`sys.path[0]` and printed `IMPORTED: <worktree>/src/claude_code_hooks_daemon/__init__.py`.

- RED (before fix): `6 failed, 10 passed` in `test_pipe_blocker_literal_pipe_text.py`
- GREEN: `176 passed` over `test_pipe_blocker_comprehensive.py` and the new file;
  all `-k pipe` tests under `tests/unit/handlers/pre_tool_use/` were 644 pass plus
  the two inverted ones, now fixed
- ruff, black `--target-version py311`, mypy, pyright: clean on touched files
- `scripts/qa/audit_error_hiding.py`: pass; `scripts/qa/check_input_contract.py`: pass

## N285 observation

`PYTHONPATH=$PWD/src /workspace/untracked/venv-workspace-py311-81c29529/bin/python -m pytest ...`
(literal interpreter path) was allowed. This was DENIED, R-UPGRADE-APPROVAL-ENV-BYPASS:

```
cd /workspace/untracked/worktrees/worktree-n284-pipe-quoted-alt && P=/workspace/untracked/venv-workspace-py311-81c29529/bin/python; grep -c "0 errors" untracked/scratch/pyr.txt; PYTHONPATH=$PWD/src $P scripts/qa/audit_error_hiding.py > untracked/scratch/a1.txt 2>&1; ...
```

Deny text: "BLOCKED \[R-UPGRADE-APPROVAL-ENV-BYPASS\]: a Bash command that sets
`HOOKS_DAEMON_UPGRADE_HANDOFF`, or runs an upgrade with a variable that picks
its interpreter, venv, flags or code, or passes `--uv <path>` -- The upgrade and
its pre-deploy gate run as shipped, not as an agent steers them."

An earlier form, \`PY=/workspace/.../bin; PYTHONPATH=$PWD/src $PY/python -m pytest ...

> out 2>&1; tail ...`, was denied with the same rule. The shape that trips it is `PYTHONPATH=`set on a command whose interpreter is a variable or whose command is a`;\` chain; the literal-path single command passed.

## Self-hit

While working, the unfixed daemon denied my own `grep` whose pattern held
`\|HEAD` as R-PIPE-TO-HEAD (producer `TAIL\`): the N284 bug, live.
