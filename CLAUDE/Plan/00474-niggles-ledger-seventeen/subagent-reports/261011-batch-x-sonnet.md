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

## Round 2 (review FIX FIRST)

- Comprehension bypass: `_bindings` binds `ast.comprehension` targets to their iterable (list, generator, set, dict).
  Deny rows added for each shape, for append/extend/`+=`, a shell string and a bare `['pytest']`.
- Literal hidden module-wide: lists are keyed by (function, name) (`_function_scopes`); only the literal of the last
  replacing assignment before a running call is set aside. Two-function deny rows added (both orders).
- Quadratic cost: `_list_changes` sorts once; `_states_after` is one sweep per list; alias roots memoised in a set;
  at most 64 words per call; words charged to the parse meter (past it, lists are judged as written). Timing tests: the
  reviewer's 3000-alias/300-run and 2000 append-and-run scripts finish in under 1.5 s.
- Perf (perf2.sh, branch vs main, noisy host): alias chain 40 KB 0.44 s vs 0.15 s; alias fan 0.32 s vs 0.18 s;
  2000 append-run 0.46 s vs 0.19 s (was 15.1 s, 7.2 s, 5.8 s). perf.sh n=500: interleaved 0.22 vs 0.10, async spread
  0.29 vs 0.26, exec_many 0.14 vs 0.17.
- Renamed the directory test to `..._is_absent_like_a_script` and asserted both None; added a FIFO test asserting both deny.
- `run_path` is `runpy.run_path` (aliased module, or imported name) only; `router.run_path(...)` runs nothing.
- Also read: `exec(compile(open(f).read(), ...))`, `with open(f) as h: exec(h.read())`.
- Probes (run2.sh, branch vs main): test_probe_x 14 failing on branch vs 27 on main; x2 4 vs 5; x3 0 vs 2; x4 4 vs 4
  (param/loop allow cases, pre-existing false denies identical on main). Every row failing on the branch also fails on
  main; no row is weaker than main.
- Checks: handler tests plus corpus gate 1683 passed; black, ruff, mypy, pyright clean.

## Left

- Absent file named by exec/run_path allows (above).
- Only the five subprocess sinks follow a mutated list; `os.execv*`, `pty.spawn`, `list.insert`, `a = a + [...]` are
  not tracked.
- A path computed at run time keeps the pre-existing fail-closed `exec` handling (denied as a bare pytest unless a
  path-shaped literal exists).
