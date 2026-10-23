# N531: the child pytest does not exit on CI py3.12 (investigation, partial)

Worktree `untracked/worktrees/worktree-n531-child-exit`, branch `worktree-n531-child-exit`, base `c4a552d35`.
I stopped at the 150k context soft budget with the cause NOT proved. No code is changed: the commit records
the ledger update only. This file is also the handoff.

## Proved

- **The test ran at 43% of the suite, not 99%.** In run 39883575808 the test's progress line
  (`test_project_containment.py`, row 3) jumps from `02:45:20.86` to `02:46:22.15`, which is the 60 s
  timeout. The first run (39853605423, job 120086055234) has the same shape at line 1839. The failure
  block is printed at the end of the run, which is why it looked like 99%.
- **The child was still alive at 60 s.** Python 3.12 `subprocess.run` handles a timeout with
  `kill()` → `send_signal()` → `poll()`, and only signals if `poll()` reaps nothing. A child that had
  already exited would have been reaped with returncode 0. Both logs show `returncode: -9`. The child's
  stdout ended at `\n2 passed in 0.43s\n` (0.60s in the second run), and its stderr was empty. So the hang
  is after the summary line: `pytest_unconfigure`, atexit, or interpreter finalisation.
- **CI and local tool versions are the same**: pytest 9.0.3, pytest-cov 7.1.0, coverage 7.13.5
  (the job log install list and its `plugins:` line), with no xdist.

## Disproved (locally, Python 3.11, same packages)

- **Coverage inheritance.** The `pytest_cov` package source contains no `environ` or `subprocess`
  handling, and coverage's subprocess patch only runs when `[tool.coverage.run] patch` is set, which
  pyproject does not do. The probe in `untracked/scratch/n531/n531_exit_probe.py` was loaded into
  parent and child through `PYTEST_ADDOPTS`, with the parent run under `--cov=src`. In the child it showed:
  no `COV*`/`COVERAGE*` variable, `coverage` not imported, only `MainThread` alive at `pytest_unconfigure`,
  and two atexit registrations, `shutil.rmtree` (the doc-write jail's log dir) and
  `_pytest.pathlib.cleanup_numbered_dir`. With `CI=true GITHUB_ACTIONS=true HOOKS_DAEMON_RELEASE_GATE=1`
  added, the child still exited normally and fast (`2 passed in 0.70s`, rc 0). I did not time the
  exit itself.
- No conftest or plugin in the child does exit-time work beyond those two:
  `deny_carries_rule_id.pytest_unconfigure` only restores methods, and `full_qa_gate` has no exit hooks.

## Leading hypothesis (inference, not proved)

Pytest's exit-time `cleanup_numbered_dir(/tmp/pytest-of-<user>, "pytest-", keep=3, ...)` runs in every
child pytest. It `rm_rf`s each numbered basetemp outside the newest three that has no live `.lock`, and
retries every `garbage-*` directory. On CI every child pytest the suite spawns (see call sites below)
shares that root with the parent. The child's exit cost therefore depends on what earlier children left.
This fits the evidence: the hang is after the summary, it depends on state and order, and no threads are
alive. It does NOT explain why only py3.12 fails, and I have no CI measurement of it.

## Left

1. Get evidence from CI: in the shared helper, arm `faulthandler.dump_traceback_later(<well under the timeout>, file=sys.stderr)` in the child, from a `-p` plugin's trylast `pytest_unconfigure`. A
   recurrence then prints the child's stack into `TimeoutExpired.stderr`. It is diagnostics, not a fix.
2. The likely fix, defensible even before proof: give each child pytest its own `--basetemp` under the
   parent's `tmp_path`, so its exit cleanup touches only its own tree. Also pass an explicit environment
   so the child inherits nothing incidental from the parent run. Do this through ONE shared helper in
   `tests/support/`, test-first. The RED test: a child spawned with a pre-seeded large unlocked
   `pytest-N` in a fake `PYTEST_DEBUG_TEMPROOT` spends its exit deleting it, and with the helper it does not.
3. Child-pytest call sites that should use the helper:
   `tests/unit/handlers/pre_tool_use/test_project_containment.py:1355`,
   `tests/test_claude_code_hooks_daemon_full_qa_gate_loader.py:53`,
   `tests/unit/qa/test_full_qa_gate.py:69` (and the wrappers at :114/:138),
   `tests/unit/qa/test_run_test_matrix.py:521`, `tests/unit/qa/test_first_error_lines.py:183/213`,
   `tests/integration/test_blocking_gate_skip_guard.py:185`,
   `tests/integration/test_relay_gate_skip_guard.py:127`,
   `tests/integration/test_project_context_isolation.py:60`. Each needs checking: some of these may be
   argv assertions rather than spawns.
4. Update N531 when the cause is proved, then run `run_autofix.sh` and
   `llm_qa.py changed --range c4a552d35..HEAD --allow-unmapped`.

## State

- N531 in NIGGLES.md is updated with the coordinator's correction ("two of the three full runs that
  reached it failed"), the 43% fact, the disproof and the lead. Its STATUS-INDEX row is updated and
  status stays 🔄 in progress.
- The second job log (first failure) is saved as `untracked/scratch/n531/ci-first-312.log`. The probe
  and its outputs are in `untracked/scratch/n531/` (gitignored).
- QA: not run. The commit changes only plan markdown.

## Part 2 (interrupted by host reboot; WIP)

Left: RED tests only, at `tests/unit/support/test_child_pytest.py`. They are not run yet and the helper does not exist.
Still to do: `tests/support/child_pytest.py` (`run_child_pytest`, `ChildPytestError`, `HELPER_OWNED_ENV_KEYS`,
`WATCHDOG_FRACTION`), plus a watchdog `-p` plugin in its own dir `tests/support/child_pytest_plugin/`. The plugin
dups fd 2 at import, arms `dump_traceback_later` at configure and re-arms it at trylast unconfigure against a
wall-clock deadline passed in an env var. Its `-p` and `--basetemp` go in through `PYTEST_ADDOPTS`, so launchers are
covered as well. After that: move the 9 call sites, update N531, autofix, then targeted QA.

## Part 2 (resumed after the reboot; done)

**RED confirmed**: at 12e965cc6 the module failed to import (`No module named 'tests.support.child_pytest'`),
which is the right reason. No RED assertion was changed. One literal was renamed: `timeout=0` became the named
`_NON_POSITIVE_SECONDS`, because the `magic_values` QA check flagged it. The test still checks the same thing.

**Helper** (`eedebf4f6`, all 19 helper tests pass):

- `tests/support/child_pytest.py`: `run_child_pytest(args, *, cwd, tmp_path, timeout=Timeout.REQUEST_LONG, expected_returncode=0, explain, extra_env, pythonpath, launcher, pass_fds)`, plus `ChildPytestError` (an
  `AssertionError` that carries the child's stdout and stderr), `HELPER_OWNED_ENV_KEYS` and
  `WATCHDOG_FRACTION = 0.75`.
- The child's environment has two parts. One is a fixed allowlist: PATH, HOME, USER, LOGNAME, LANG, LC_ALL, LC_CTYPE
  and TMPDIR. The other is `extra_env`, which may not set a key the helper owns. The helper sets PYTEST_ADDOPTS
  (`-p child_pytest_watchdog --basetemp=<tmp_path>/.child-XXXX`), PYTHONPATH (the plugin dir followed by the
  caller's entries), PYTHONUNBUFFERED, and the watchdog deadline.
- `tests/support/child_pytest_plugin/child_pytest_watchdog.py` duplicates fd 2 at import, before capture starts. It
  then arms `faulthandler.dump_traceback_later` at the deadline, and arms it again at `pytest_configure` and at the
  trylast `pytest_unconfigure`. The import has no side effects unless the deadline variable is set, so the helper can
  import `DEADLINE_ENV` from it.
- Two hang tests prove the dumped stacks reach the error message: a hang inside a test, and an atexit hang after the
  summary, which is the N531 shape.

**Call sites moved**:

- `808c3d4f2`: the N531 pair test, `test_project_containment.py`, moved first. The same commit moved
  `test_claude_code_hooks_daemon_full_qa_gate_loader.py` and every child pytest in `tests/unit/qa/test_full_qa_gate.py`.
  That covers `_run_pytest_subprocess`, the bash and `python -c` launchers through `launcher=`, and the simulated
  xdist `_run` with `pass_fds` and an extra PYTHONPATH entry.
- `bb77f42b1`: `test_first_error_lines.py` (both sites), `test_run_test_matrix.py` (coverage measurement, with
  COVERAGE_FILE passed through `extra_env`), `test_blocking_gate_skip_guard.py`, `test_relay_gate_skip_guard.py` and
  `test_project_context_isolation.py`.
- Every site now pins its exact expected exit code instead of `!= 0` or no check at all. The two xdist runs that
  are not refused exit 5, because they collect nothing.
- Sites that had no timeout before now get one: 60 s by default. `run_test_matrix` gets `scaled_seconds(60)` and the
  context-isolation pairs get `scaled_seconds(120)`. No site's existing timeout was raised.
- The python `-c` subprocess in the loader test is not a pytest child, so it was left alone.

**N531 ledger** (`eb83aa16b`): NIGGLES.md records the change as a mitigation plus diagnostics, says the cause is not
proved, and keeps the status at 🔄 until a CI full run passes. The STATUS-INDEX row is rewritten shorter and keeps the
same column count as every other row. The large whitespace diff in that file comes from the table formatter
narrowing the column.

**QA**: `run_autofix.sh`, then
`llm_qa.py changed --range c4a552d35..HEAD --allow-unmapped` at `0f5d7ee3a` gave `QA: 41/41 PASSED`
(changed_tests: 442 passed). The first run failed only on the `magic_values` literal described above.
Two files are unmapped: the two `__init__.py` files.

**Head**: the commit that adds this section. Everything is pushed to `origin/worktree-n531-child-exit`.
