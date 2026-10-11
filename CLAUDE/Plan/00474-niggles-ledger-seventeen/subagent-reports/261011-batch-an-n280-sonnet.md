# Batch AN, N280: a test run must never change a tracked file of any checkout

Worktree `worktree-batch-an-n280`. Code commit `fd85826ff`.

## Verdict

**No test route to the main checkout's `CLAUDE.md` was found**, statically or by experiment.
The cause of the original event stays unproven. What is now impossible is the outcome: a
test run, and any Python it spawns, can no longer write, rename over or delete
`CLAUDE.md` or `.claude/HOOKS-DAEMON.md` in any checkout of this repository, and a test that
tries fails by name even if the writer swallows the error.

## Static audit

- The only writers of the generated docs are `ClaudeMdInjector` (reached from
  `DaemonController.initialise()`, so from `cmd_start` and `cmd_regenerate_docs` through
  `_build_initialised_controller`) and `DocsGenerator` (`generate-docs`,
  `regenerate-docs`). A live daemon never re-runs `initialise()`; `process_event` only calls
  it when `_initialised` is false.
- Project root for those commands is `--project-root`, else `get_project_path()`, which walks
  up from `Path.cwd()` to the first `.claude/` that is not inside a daemon clone. It reads no
  environment variable. `CLAUDE_PROJECT_DIR` is not consulted by any resolver (the only
  uses in `src` are text in guidance strings and hook command templates).
  No resolver uses `git --git-common-dir`.
- So the one ambient input is the process cwd. An agent shell's cwd is reset between calls,
  so a worktree test run started from `/workspace` resolves the MAIN checkout. That is the
  candidate that fits "older code than main, written into main, daemon pid unchanged".

## Experiment that tests the cwd candidate

A faithful clone of this worktree (`untracked/scratch/decoy`, a real git repo with the full
`.claude/` and `CLAUDE.md`) stood in for "main". Every test directory was run with the
worktree's tests and venv but **cwd = the decoy**:

| Run | Selection                                                                                     | Result                                                                         | Decoy            |
| --- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ---------------- |
| 1   | unit/daemon, unit/qa, injector tests (partial decoy)                                          | 4746 passed, 22 failed (decoy lacked venv state)                               | docs untouched   |
| 2   | unit/daemon, qa, core, install, scripts                                                       | 4692 + 5223 passed                                                             | clean, no commit |
| 3   | integration, acceptance, config, daemon, handlers, root tests                                 | 7063 passed                                                                    | clean, no commit |
| 4   | unit/handlers, docs_qa, plan_qa, config, constants, utils, strategies, supervise and the rest | 16820 + 9679 + 4451 passed; 4 failures, none caused by this change (see below) | clean, no commit |

Result: **no test wrote the decoy's `CLAUDE.md`, `HOOKS-DAEMON.md`, or committed to it**. The
only cwd-dependent writes are two untracked directories (`untracked/config-changes/`,
`untracked/truth-changes/`, both gitignored upgrade-report output). Many tests do resolve the
project from cwd (`test_cli_check`, `test_cli_verdicts`, `cmd_restart` with start/stop
mocked), which is a real isolation hole, but none of them reaches a doc writer.

The four failures in run 4 are unrelated to this branch: `test_wall_clock_bounds_are_load_scaled`
(bare `1.5` bounds in `test_subagent_full_qa_blocker.py`), `test_handler_options_accessor`,
`test_scope_requires_agent_id_event`, and one teardown error from a test that patches `open`
(that one WAS this change; fixed, see below).

The whole suite was also run once with the jail armed (below): integration + acceptance
6556 passed, units 30,950 passed, with **zero refusals**. No existing test writes a generated
doc of this checkout, the main checkout or any other worktree.

## The structural defence

`tests/jail_site/doc_write_jail.py` (stdlib only), armed at import by `tests/conftest.py`:

- A `sys.addaudithook` hook refuses write-mode `open`, `os.rename` (either side) and
  `os.remove` on `CLAUDE.md` and `.claude/HOOKS-DAEMON.md` of **every checkout**, read from
  `git worktree list --porcelain`. A run in a linked worktree therefore protects main.
- It resolves symlinks for opens; renames and deletes act on the link itself.
  `shutil.rmtree`'s directory-fd unlinks are resolved through `/proc/self/fd`.
- The protected paths and a refusal log go to child interpreters through the environment,
  and `tests/jail_site/sitecustomize.py` (put on `PYTHONPATH`) arms each one. A CLI a test
  spawns (`regenerate-docs`, `start`, a nested pytest) is covered with no production change.
- Refusals are appended to a log with `os` primitives. A new autouse fixture,
  `no_test_writes_a_generated_doc_of_any_checkout`, fails the test if the log grew, so a
  writer that catches `PermissionError` (the injector does) still fails the test that caused it.
- The protected names are one constant, `PROTECTED_RELATIVE_PATHS`, which the existing guard
  now reads. The existing per-test restore guard and its tests are unchanged (the fixture was
  NOT weakened; its own restore runs inside `jail.allowed()`).

Tests: `tests/unit/test_doc_write_jail.py`, 27 tests. They include a real child interpreter
and `cmd_regenerate_docs` run in a subprocess against a protected project (it changes nothing
and logs the refusals), worktree discovery against a real `git worktree add`, and the fixture
failing on an unconsumed refusal. RED was `ModuleNotFoundError: No module named 'tests.jail_site'`.

Two real defects found and fixed by running the jail against the suite:

1. A test patching `open` broke the fixture's teardown read. Reads and appends now use `os`
   primitives.
2. `shutil.rmtree` unlinks bare names relative to a directory fd; resolving them against the
   cwd gave a false refusal in five integration tests whenever cwd held a protected file.
   Fixed and pinned by two tests.

## Cost and limits

- Cost: one `git worktree list` at import; a path resolution per write-mode `open`
  (microseconds); one stat per test. Integration + acceptance ran in 23.5 minutes with it.
- Does not see: a Python started with `-I` or `-S`; a test that clears the environment; a
  non-Python process (`cp`, `sed`, `git checkout`); an `os.open(..., dir_fd=...)` of a relative
  name; an `os.truncate`. The existing restore guard still backs these for the own checkout.
- `test_start_waits_on_a_slowly_initialising_daemon.py` supplies its own `sitecustomize`
  via `PYTHONPATH`, which shadows the jail in that one child. Harmless there (its project is a
  tmp dir).

## Not done, and why

- The original event is not explained. Remaining untested candidates: a daemon started from
  an older tree, and a non-test process. Neither is a test route; the jail does not touch
  them. The standing rule not to restart the daemon during a test run stands.
- `llm_qa.py changed` reports `tests/conftest.py` and `tests/jail_site/doc_write_jail.py` as
  unmapped `too-broad` (a conftest and anything it imports reach every test). That is by design for
  every conftest-imported helper; it passes with `--allow-unmapped`, the coordinator's full
  gate being the cover. The one remaining QA finding is the unrelated plan_qa
  `journal-freshness` advisory for plan 00495.
- I added two rules to `scripts/qa/changed_tests_map.yaml` so a change here runs the jail and
  guard tests.
- Another batch's pytest runs were live on the host throughout, so the "pytest clear" check could
  not be satisfied; none of my runs touched a daemon, and none wrote outside this worktree.
- Commit `fd85826ff`'s message carries a stray `Addresses #0` line and lacks the
  Co-Authored-By trailer (amend is blocked by the daemon). Ignore the `#0`.
