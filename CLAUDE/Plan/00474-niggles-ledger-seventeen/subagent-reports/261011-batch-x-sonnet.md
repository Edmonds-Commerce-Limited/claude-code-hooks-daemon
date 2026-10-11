# Batch X: N409 residual false negatives in subagent_full_qa_blocker

## Changes (src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_full_qa_blocker.py)

- `_grown_list`, `_bindings`, `_process_arguments`: `.append(x)` / `.extend(xs)` no longer pass their argument on as
  a call argument; the argument is bound to the receiver name instead, so it is reached only when the list is.
  A user-defined `append` is not treated as a grower. This also removes a pre-existing false deny: a list that is
  grown and never run no longer reaches its `"pytest"` literal.
- `_list_changes`, `_list_before`, `_alias_roots`, `_grown_argvs`: the argv a named list held at a
  `Popen`/`run`/`call`/`check_call`/`check_output` call (first arg or `args=`, through `b = a` aliases) is judged,
  and the literal the name started from is not judged on its own (it was only the first part; `['pytest']` then
  `.append('tests/unit/x.py')` was wrongly a bare pytest). `asyncio.create_subprocess_exec(...)` words (including a
  `*named_list` spread) are judged as an argv. `create_subprocess_shell` already judged as shell text.
- `_files_run_in_process`: `exec(open('f').read())`, `exec(Path('f').read_text())` and `runpy.run_path('f')` yield
  `_CODE_FILE` with the named file, so it is read and judged exactly like a `python3 f` operand
  (`_full_run_in_code_file`: absent allows, unreadable or written-this-command denies, targeted allows).

## Tests

- `TestResidualPythonRoutesToAFullRun` in tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py:
  18 deny rows, 14 allow rows (data only, printed, mutated-never-passed, targeted pytest via append/+=/extend,
  targeted asyncio, user-defined `append`), file-judgement cases for exec and run_path (full, targeted, absent,
  unreadable-as-directory consistent with `python3 file`).
- Corpus rows `n409-python-heredoc-mutated-list-never-run`, `-mutated-list-targeted-pytest`,
  `-asyncio-targeted-pytest`.
- Red before the fix: 21 failed; green after.

## Counts

- Handler test file plus corpus gate: 1662 passed, 0 failed (the gate gained 3 rows).
- black, ruff, mypy, pyright (changed src file): clean.

## Probe (/workspace/untracked/scratch/review-batch-i/test_probe.py, repointed at this worktree's tests)

33 of 34 CASES deny, including `append`, `pluseq`, `extend`, `asyncio`. Failing: `exec_open` only. Its `runner.py` does not
exist in the repo root, and a missing script is allowed by the handler's existing policy (`python3 runner.py` with no
such file allows; the process would fail before running anything). With a `runner.py` that runs a full suite present,
it denies (tested with a tmp_path file). No other probe CASE fails (the baseline for the other CASES was not run).

## Left

- Absent file named by exec/run_path allows (above).
- Only the five subprocess sinks follow a mutated list; `os.execv*`, `pty.spawn`, `list.insert`, `a = a + [...]` are
  not tracked.
- A path computed at run time keeps the pre-existing fail-closed `exec` handling (denied as a bare pytest unless a
  path-shaped literal exists).
