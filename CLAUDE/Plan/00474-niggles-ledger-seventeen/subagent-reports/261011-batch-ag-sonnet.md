# Batch AG: N417, `pytest` text in Python string data

Branch `agent-a4ebfbbe877af6ea0-69432ca3`, from main 203a21653.

## Reproduction

`python3 - <<'EOF'` with `import subprocess; subprocess.run(['ls'])` and any of
`check(c)`, `record('<pytest cmd>')`, `T['a']` handed to an unknown call: denied
`pytest-whole-suite`. Probe files `probe_ae_shell2.py` and `probe_ae_shell.py`
(run as heredoc and as a script file) denied on main.

## Cause

`_process_arguments` (N409, commit f2ada97ec) seeded the reach walk from the
arguments and receiver of every call except `_TEXT_SINKS` and list changers.
`git log -S_TEXT_SINKS` shows no ruling that an unknown call may run its
argument; N409 only narrowed from "every literal" to "every literal some call
receives".

## Change (`subagent_full_qa_blocker.py`)

- `_CallRanker` ranks each call: RUNS (process/code sinks, aliases and variables
  bound to them, `partial(sink, ...)`, `p.stdin.write`, and script functions,
  methods, classes and lambdas that lead to one, fixed point over the call
  graph), CARRIES NOTHING (data calls, text sinks, `re.compile`, script
  functions that never call out), MAY RUN IT (any other call).
- `_process_arguments` returns `(runs, maybe)`; `_parsed_reach`,
  `_passed_literals`, `_python_strings`, `_python_strings_of`,
  `_pytest_in_code` carry both.
- Strings reaching only a MAY call are yielded wrapped in `_MAY_BE_RUN`;
  `_first_full_run` unwraps and converts a positive match into an unseen one
  (`_HANDED_ON_REASON`), so it is an advisory by default and a deny under
  `unseen_policy: deny`. State-changing programs (cd, writes) are skipped there.
- Positive matches elsewhere still win over the unseen one.

## Results

- `probe_ae_shell2.py` / `probe_ae_shell.py`: deny on main, unseen advisory now.
  `probe_ae_lines.py`, `probe_ae_wrappers.py`: allow, unchanged.
- Tests: `test_subagent_full_qa_blocker.py`, `test_ordinary_command_regression_gate.py`
  1888 passed; corpus and deadlock gate files 357 passed. New class
  `TestStringsOnlyCountAtAProcess` (23 cases). black clean, ruff clean, pyright
  clean on the changed source (the test file's `pytest` import is unresolved in
  this venv, as before).
- Cost: call-graph pass is one walk plus a worklist (each rank rises at most
  twice); 250/500 chained functions 0.14s/0.19s.

## Residuals

Name-only matching (a script function named `run` is the sink `run`, which only
over-denies); a string given to an unknown imported function is an advisory by
design; `f.write(text)` to a non-stdin file is unseen.
