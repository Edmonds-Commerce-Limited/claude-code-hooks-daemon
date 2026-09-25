# Category: unproven signal target

**Defence**: `scripts/qa/check_signal_targets.py` — a nonzero signal
(`os.kill`, `os.killpg`, `signal.pthread_kill`, a `psutil` process handle's
`terminate`/`kill`/`send_signal`, or a `kill`/`pkill`/`killall` argv run
through `subprocess`) whose target pid was not proven to be the intended
process.

Index: [README.md](README.md). Found by the infra owner after the container
died twice with exit 137 (Plan 00466 N59).

## The class

A signal is only as safe as the proof that its pid names the process the code
means. A defect belongs here when a nonzero signal goes to a pid whose identity
rests on anything weaker than one of these proofs:

| Proof                                                                       | Where it lives                                                                                             |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| The command line is a daemon server for THIS project root                   | `utils/safe_signal.py` `verified_daemon_process` and callers                                               |
| A pid from `read_pid_file(..., verify_daemon=True)`                         | `daemon/paths.py`; the Detector accepts it unrebound                                                       |
| A still-running child we spawned that leads its own group                   | `utils/safe_signal.py` `signal_own_session_child`                                                          |
| A `subprocess.Popen` object's own methods                                   | Popen signals only its own unreaped child                                                                  |
| A shell pid whose parent, or start time, is unchanged since it was recorded | `resolve_venv.sh` `_rv_parent_of`, `venv.sh` `_venv_parent_of`, `venv_bootstrap.sh` `_vb_process_identity` |

What is NOT proof:

- **An `int` above 1.** A `MagicMock` pid coerces to 1 through `__index__`, and
  so does `True`. `os.killpg(os.getpgid(1), SIGKILL)` is init's group.
- **A PID file.** It survives a container restart, and a restarted container
  reuses small pids, so a stale file can name Claude Code itself.
- **`kill -0` succeeding.** It proves some process has the pid, not which one.
- **A process group of a process that does not lead it.** A daemon's group is
  its long-gone session leader's; it could be init's or ours.
- **A pid a background job had, after the job ended.** Once reaped, the pid is
  free for reuse.

Signal 0 delivers nothing and is exempt everywhere.

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
| `scripts/upgrade.sh` `_stop_running_daemons`           | SIGTERM to any live pid a `daemon-*.pid` file held                   | review   | dc7ab0e0     |
| `scripts/dummy-client-repo.sh` teardown                | `kill -- -<pgid>` of a group the daemon does not lead                | review   | dc7ab0e0     |
| `scripts/venv_bootstrap.sh` `_vb_watchdog`             | TERM at the bound to whatever process held the build's pid           | review   | dc7ab0e0     |
| `scripts/install/venv.sh` `venv_heartbeat_stop`        | TERM to a heartbeat pid minutes after the heartbeat ended on its own | review   | dc7ab0e0     |
| `scripts/lib/resolve_venv.sh` probe watchdog           | KILL at the bound to a probe pid `wait` had already reaped           | review   | dc7ab0e0     |

"review" in the Defence column means no Detector covers the site; see below.

## What the Defence does not catch

- **Shell.** The Detector reads Python only. The five shell instances above
  were found by a manual search and are pinned by their own tests. A new
  `kill "$pid"` in a `.sh` file is found by review and nothing else.

- **Tests.** The Detector does not scan `tests/`. The session net refuses the
  catastrophic targets. It does not protect an unrelated process that a test
  signals by a pid its code under test reported:

  - `tests/venv_bootstrap_sandbox.py` cleanup now checks that the stand-in's
    environment still names its own sandbox before it signals.
  - `tests/integration/test_venv_bootstrap_driver.py` now checks that a
    build pid the driver reported still carries the test's own `HOME` before
    it signals.
  - A new test site of either shape is found by review alone.

- **Data flow beyond one scope.** A pid is proven by a binding in the same
  function. A verified pid passed as a parameter is reported, which is a false
  positive and the safe direction. The Detector found none on the tree.

- **Aliased receivers.** `.terminate()`/`.kill()` on a handle that is not
  visibly bound from `psutil.Process(...)` or `psutil.process_iter()` in the
  same scope is not reported, because those names are too common to judge by
  name alone. For example, `self._proc = psutil.Process(pid)` in one method and
  `self._proc.kill()` in another is not reported.

- **Own-child shell pids, judged by construction rather than checked.** Three
  shell sites signal a `$!` with no identity check, because the signal can
  only be sent while that child is alive:

  - The skill installer's aside heartbeat loops until its owner dies, and only
    that owner stops it.
  - The inner `sleep` of each heartbeat is signalled from the heartbeat's own
    TERM trap. A trap runs either during `wait`, when the sleep is still
    alive, or in the instant after `wait` has reaped it.
  - `resolve_venv.sh`'s own watchdog is stopped the same way.

  In that instant, reusing the pid would need the kernel's pid counter to wrap
  the whole pid space, and allocation is sequential. The Detector does not
  read shell, so a new site of this shape would be judged by review alone.
