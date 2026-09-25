# Category: unproven signal target

**Defence**: `scripts/qa/check_signal_targets.py`, run as llm_qa
`signal_targets` (check 33 in `run_all.sh`). It reports a nonzero signal whose
target pid was not proven to be the intended process. Its four rules:

| Rule id                   | What it reads                                                                                                                                               |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `raw-signal`              | Python `os.kill`, `os.killpg`, `signal.pthread_kill`, however imported                                                                                      |
| `unproven-process-handle` | Python `terminate`/`kill`/`send_signal` on a `psutil` handle built from a raw pid or `process_iter()`, and `send_signal` on anything not a Popen we spawned |
| `kill-command`            | A `kill`/`pkill`/`killall` argv run through `subprocess`                                                                                                    |
| `shell-unproven-kill`     | `kill`/`pkill`/`killall` in every tracked `*.sh`/`*.bash` and shell-shebang script outside a `fixtures`/`assets` directory                                  |

Index: [README.md](README.md). Found by the infra owner after the container
died twice with exit 137 (Plan 00466 N59).

## The class

A signal is only as safe as the proof that its pid names the process the code
means. A defect belongs here when a nonzero signal goes to a pid whose identity
rests on anything weaker than one of these proofs:

| Proof                                                                 | Where it lives                                                                                                                                                                                                     |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| The command line is a daemon server for THIS project root             | `utils/safe_signal.py` `verified_daemon_process` and its callers                                                                                                                                                   |
| A still-running child we spawned that leads its own group             | `utils/safe_signal.py` `signal_own_session_child`                                                                                                                                                                  |
| A `subprocess.Popen` object's own methods                             | Popen signals only its own unreaped child                                                                                                                                                                          |
| A shell identity check run earlier in the same function as the `kill` | `upgrade.sh` `_is_project_daemon_pid`, `dummy-client-repo.sh` `_is_dummy_daemon_pid`, `venv_bootstrap.sh` `_vb_process_identity`/`_vb_job_running`, `venv.sh` `_venv_parent_of`, `resolve_venv.sh` `_rv_parent_of` |
| A shell `$$`, `$!`, `%job`, or a variable bound only from `$!`        | The shell's own process and its own background job                                                                                                                                                                 |

What is NOT proof:

- **An `int` above 1.** A `MagicMock` pid coerces to 1 through `__index__`, and
  so does `True`. `os.killpg(os.getpgid(1), SIGKILL)` is init's group.
- **A PID file.** It survives a container restart, and a restarted container
  reuses small pids, so a stale file can name Claude Code itself.
- **`read_pid_file(..., verify_daemon=True)`.** It proves the pid is *a* hooks
  daemon, not this project's: `cmd_stop` sent SIGTERM to another project's
  daemon through it.
- **`kill -0` succeeding.** It proves some process has the pid, not which one.
- **A `pgrep` match, some moments later.** The pid can have been reused since.
- **A process group of a process that does not lead it.** A daemon's group is
  its long-gone session leader's; it could be init's or ours. In shell a group
  target (`kill -- -PGID`) is proven by an identity check only, never by `$!`
  or `$$`.
- **A pid a background job had, after the job ended.** Once reaped, the pid is
  free for reuse.

Signal 0 delivers nothing and is exempt everywhere. So is `kill -l`.

## Why a review finds it and the test suite does not

The unit tests for the crashing code passed: they mocked `subprocess.Popen`
and asserted on the mock. The mock's pid is what made the real `killpg` reach
init. A test that exercises the dangerous path with a mock is the trigger, not
the safeguard, and the first symptom was the whole container dying about ten
seconds later, with nothing in any test report.

The PID-file sites passed for the opposite reason. Their fixtures wrote the pid
of a sleeper the test had just started. That is a process the code may signal,
so the fixture could never show the case that matters: a pid that now names
something else.

`tests/conftest.py` now installs a session-wide net (`tests/signal_safety_net.py`).
It refuses, without delivering, any nonzero `os.kill`/`os.killpg` from the test
process to pid 0, 1 or -1, group 1, the test process, its group, any ancestor
or a Claude Code process. It records each refusal, so code that swallows the
error still fails its test.

## Instances

| Where                                                  | What it allowed                                                      | Defence  | Fix          |
| ------------------------------------------------------ | -------------------------------------------------------------------- | -------- | ------------ |
| N53 branch `run_git` (never merged)                    | `killpg(getpgid(MagicMock().pid), SIGKILL)` killed init twice        | 904f1c31 | N53's branch |
| `install/client_validator.py` `_check_running_daemon`  | SIGTERM then SIGKILL to any pid a `daemon*.pid` file held            | 904f1c31 | 2817ef0e     |
| `daemon/process_verification.py` `kill_daemon_process` | `psutil.Process(pid).terminate()/kill()` with no identity check      | 904f1c31 | 2817ef0e     |
| `daemon/cli.py` `cmd_stop`                             | SIGTERM to another project's daemon named by the PID file            | 548403a0 | 93d350d7     |
| `scripts/upgrade.sh` `_stop_running_daemons`           | SIGTERM to any live pid a `daemon-*.pid` file held                   | 548403a0 | dc7ab0e0     |
| `scripts/dummy-client-repo.sh` teardown                | `kill -- -<pgid>` of a group the daemon does not lead                | 548403a0 | dc7ab0e0     |
| `scripts/dummy-client-repo.sh` teardown                | SIGTERM to a pid `pgrep` had reported, without re-reading it         | 548403a0 | 93d350d7     |
| `scripts/venv_bootstrap.sh` `_vb_watchdog`             | TERM at the bound to whatever process held the build's pid           | 548403a0 | dc7ab0e0     |
| `scripts/venv_bootstrap.sh` `_vb_signal_group`         | A group kill of whatever group a caller passed                       | 548403a0 | 93d350d7     |
| `scripts/install/venv.sh` `venv_heartbeat_stop`        | TERM to a heartbeat pid minutes after the heartbeat ended on its own | 548403a0 | dc7ab0e0     |
| `scripts/lib/resolve_venv.sh` probe watchdog           | KILL at the bound to a probe pid `wait` had already reaped           | review   | dc7ab0e0     |

On main 9f83b9ff9 the shell rule reports five of the shell rows above.
The `resolve_venv.sh` row is the exception: its pid is a `$!`, which the rule
accepts; see below.

## What the Defence does not catch

- **A `$!` signalled after the job has ended.** The shell rule accepts `$!`
  and a variable bound only from `$!`, as its own child. That is true only
  while the child is unreaped. The `resolve_venv.sh` probe watchdog was this
  shape: a detached subshell KILLed `$!` at a bound, after `wait` could
  already have reaped it. It is fixed with a parent check. A new site of that
  shape passes the Detector and is found by review alone. The rule that would
  catch it, "`$!` signalled from a scope that cannot see the job still
  running", is named and not built.

- **Tests, except a narrow named exception.** The Detector scans `tests/`
  like any other first-party tree (only a `fixtures`/`assets` directory is
  excluded, as fixture content, not code). A handful of sites deliberately
  signal a hazardous target on purpose, and are listed by path with a
  one-sentence reason in `check_signal_targets.py`'s
  `_SIGNAL_HAZARD_TEST_EXCEPTIONS` — not a directory-wide carve-out, so a new
  hazardous call anywhere else under `tests/` is still caught:

  - `tests/unit/test_signal_safety_net.py` — the safety net's own tests:
    each call is preceded by an installed-net check that it will refuse the
    target, and the net intercepts the call before the OS ever sees it.
  - `tests/venv_bootstrap_sandbox.py` cleanup checks that the stand-in's
    environment still names its own sandbox immediately before it signals.
  - `tests/integration/test_venv_bootstrap_driver.py` checks that a build
    pid the driver reported still carries the test's own `HOME` immediately
    before it signals.
  - `tests/unit/supervise/test_supervisor.py` — `pthread_kill` targets only
    this process's own main thread id, never another process. The Detector
    does not (yet) recognise that shape generally: `signal.pthread_kill` is
    still `raw-signal` for every other file, and a general carve-out for a
    proven own-thread target is named but not built (see the DBF report's
    "extend the rule" referrals).
  - The session net (`tests/signal_safety_net.py`) still separately refuses
    the catastrophic targets at runtime; it does not protect an unrelated
    process that a test signals by a pid its code under test reported, which
    is why the four sites above are proven at the call site, not only netted.

- **Data flow beyond one scope.** A Python pid is proven only through the
  helper, and a shell pid only by a check in the same function. A pid proven
  by a caller and passed in is reported, which is a false positive and the
  safe direction. The Detector found none on the tree.

- **A shell check that does not gate the kill.** The shell rule requires an
  identity check on the same variable earlier in the same function. It does
  not prove that the check's result decides whether the `kill` runs.

- **Aliased receivers.** `.terminate()`/`.kill()` on a handle that is not
  visibly bound from `psutil.Process(...)` or `psutil.process_iter()` in the
  same scope is not reported, because those names are too common to judge by
  name alone. For example, `self._proc = psutil.Process(pid)` in one method and
  `self._proc.kill()` in another is not reported.

- **Shell outside the lexer's grammar.** The shell rule splits commands by
  quoting, `$( )`, backticks, redirections, heredocs and comments; it is not a
  full shell parser. A `kill` built into a string and run through a variable
  (`"$cmd" "$pid"`) is not seen. `trap`, `eval` and `sh -c` string arguments
  are read as code.
