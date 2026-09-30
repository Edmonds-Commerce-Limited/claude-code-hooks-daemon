# Plan 00463 fix round 4 (Opus 5.5)

## Round 4

Base: c1854902c (merges main 84afc8804, N110). This fixes the six integration failures that the merge commit lists.

### Step 1: coverage (commit 44c89b2bf)

The cause was that `addopts` named `-p claude_code_hooks_daemon.qa.full_qa_gate`. Pytest imports a `-p` plugin before pytest-cov starts, so the package `__init__` and `qa/__init__` went unmeasured.

The brief said to load the plugin the way N110 does, through `tests/conftest.py`. I did not do only that. `tests/conftest.py` already imports the sink's hook, and `addopts` carried the `-p` for one reason: round 10 M1, where `--noconftest` drops every conftest route. `test_noconftest_alone_evades_the_gate_today` proves that. Relying on conftest alone would have reopened M1.

Fix: `addopts` now names a top-level module, `src/claude_code_hooks_daemon_full_qa_gate_loader.py`. It imports nothing from the package and registers the sink in `pytest_configure`, which runs after coverage has started.

- It uses `register`, not `import_plugin`. With `import_plugin`, a run where a conftest had already imported the sink raised `PytestAssertRewriteWarning`.
- It still honours `-p no:<sink>`, which `hooks-daemon test-project-handlers` relies on.
- It skips a name that is already registered, because registering a name twice raises.
- `py-modules` in `pyproject.toml` ships it in wheels.

Tests:

- `tests/test_claude_code_hooks_daemon_full_qa_gate_loader.py` is new. It sits at the tests root because `tdd_enforcement` only looks there for a top-level module. It checks:
  - importing the loader imports no package module;
  - `addopts` names only the loader;
  - the sink is registered in this run and under `--noconftest`;
  - `-p no:<sink>` unloads it;
  - naming the sink and the loader together does not register it twice.
- `TestDoubleRegistrationIsANoOp` now also asserts there is no rewrite warning.
- `TestThePluginLoadsAfterCoverageStarts` passes. Its docstring now explains that both measurements inherit `addopts` and so cover the sink. A new test in the class pins that `addopts` loads the loader and that the sink is registered.
- RED proven on mutants in `untracked/scratch/p463r4-mut/`:
  - `import_plugin` gives the warning, and the new assert catches it;
  - `register` without the guard fails the double-registration test.

### Steps 2 and 3 (commit 9ec8a6959, one commit because they share a test file)

- **Step 2.** `run_test_matrix.py` is now a declared `full_qa_patterns` entry, `run-test-matrix`, in `.claude/hooks-daemon.yaml`. A sub-agent is denied it by that pattern, not by reading its code. The main thread is never admitted (scope=SUB).
  - Why I changed the tests rather than the blocker: all three failing tests assert "a sub-agent may run it". That is the opposite of the ruling. The script also parses no arguments, so `--help` runs the whole matrix.
  - The `scripts/qa/*.py` parametrisations now leave it out, just as the `.sh` ones leave out `run_all.sh` and `run_tests.sh`.
  - New tests: the deny with pattern id `run-test-matrix`, the main-thread non-admission, a parametrised deny for every full-by-design script, and `_FULL_RUNS` rows.
  - RED: without the entry, the match comes from reading the code (id `run-tests`), not the declared pattern.
- **Step 3.** `--first-error-lines` is added to `PYTEST_VALUE_OPTIONS`, and the pinned-grammar test passes. New rows show the next word is never read as a test path.
  - The behaviour rows already held before the fix, because of the unknown-flag fallback. What went RED was the membership assert and the pin test.

### Checks

- Targeted files pass:
  - loader, `test_full_qa_gate`, `test_run_test_matrix`, `test_cli_test_project_handlers`;
  - both blocker files: 1296 passed;
  - 13 related files: 1035 passed.
- ruff, black, mypy and pyright are clean on every touched file, and semgrep reports no violations.
- The daemon was restarted before each commit and showed RUNNING.

### Open items for team-lead

- **Not pushed.** The branch has no upstream, and a push would publish a new branch to the public GitHub remote. I did not have authorisation for that, so it needs the user or team-lead.
- **Out of scope (N252).** `test_forty_repetitions_is_also_fast` and hostile_input `deep_eval_nesting` were not in any file I ran, and I changed neither.
- **Stale text.** `PLAN.md` (Round 10 M1 section) and earlier reports still say `addopts` names `claude_code_hooks_daemon.qa.full_qa_gate`. It now names the loader. I left the history as written.
- **Guard defect seen.** The `secret_file_guard` Bash check denied two probe commands with `R-SECRET-EVALUATION-ERROR: TooManyToEnumerateError`: a `for` loop with redirects, and a multi-line `python -c`. That is worth an issue report.
