"""Plan 00466 lifecycle round 8b: a retried hook never restarts a slow start.

A hook that finds the daemon still starting at its deadline denies
"starting; retry". The retried hook found no PID file yet, since a daemon
writes it only once its controller is initialised, so it launched a second
start. In a container that start's single-daemon enforcement stopped the
daemon still starting, whose command line proves it serves this project;
elsewhere the second daemon initialised in full before finding the first
one's socket. A start slower than the hook's deadline therefore never
finished.

Two real forwarder runs in a row against a real daemon whose controller
init is slowed past that deadline (by a ``sitecustomize`` on the daemon's
``PYTHONPATH``, as in ``test_start_waits_on_a_slowly_initialising_daemon``).
Every daemon that reaches controller init records its pid, so a second
start, or a stopped first one, shows in the record.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.paths import read_pid_file
from claude_code_hooks_daemon.daemon.process_verification import find_all_daemon_processes
from tests.daemon_teardown import stop_daemons_of
from tests.integration.test_init_sh_pretooluse_fail_closed import (
    _BASH_TOOL_INPUT,
    _FORWARDER_BODY,
    BASH,
    _make_project,
    _reason,
    _script_env,
    _stdin_text,
    _verdict,
)

#: Past the hook deadline these runs give, and inside the time a daemon may
#: make no progress before its launcher gives up waiting on it.
_INIT_DELAY_SECONDS = 7.0

#: The start deadline, in seconds of the hook's own run, that the first two
#: hooks are given: well inside the slowed init.
_SHORT_DEADLINE = 2

#: How often the test looks again while it waits on the daemon's processes.
_POLL_SECONDS = 0.2

_SLOW_INIT = f"""\
import os
import time

from claude_code_hooks_daemon.daemon import controller, enforcement

_initialise = controller.DaemonController.initialise


def _slowly(self, *args, **kwargs):
    with open(os.environ["HD_STARTED_LOG"], "a", encoding="ascii") as log:
        log.write(f"{{os.getpid()}}\\n")
    time.sleep({_INIT_DELAY_SECONDS})
    return _initialise(self, *args, **kwargs)


controller.DaemonController.initialise = _slowly

_IN_CONTAINER = os.environ["HD_IN_CONTAINER"] == "1"
enforcement.is_container_environment = lambda: _IN_CONTAINER
"""


def _write_python_wrapper(root: Path, started_log: Path, in_container: bool) -> Path:
    """The ``PYTHON_CMD`` the hooks run: this interpreter, with the slowed
    init (and the container answer) on its path. The hooks' own ``python3``
    runs are left alone."""
    customize = root / "customize"
    customize.mkdir()
    (customize / "sitecustomize.py").write_text(_SLOW_INIT)
    wrapper = root / "python"
    wrapper.write_text(
        "#!/bin/bash\n"
        f'export PYTHONPATH="{customize}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
        f'export HD_STARTED_LOG="{started_log}"\n'
        f"export HD_IN_CONTAINER={1 if in_container else 0}\n"
        f'exec "{sys.executable}" "$@"\n'
    )
    wrapper.chmod(0o755)
    return wrapper


@pytest.fixture
def root() -> Iterator[Path]:
    """A directory short enough for AF_UNIX paths; every daemon of its
    project is stopped through the verified path afterwards."""
    base = Path(tempfile.mkdtemp(prefix="hd-retry-"))
    try:
        yield base
    finally:
        project = base / "p"
        if project.exists():
            stop_daemons_of(project, grace_seconds=Timeout.PROCESS_DEATH_WAIT)
        shutil.rmtree(base)


def _hook(project: Path, env: dict[str, str], python: Path, deadline: int) -> tuple[str, str, str]:
    """One PreToolUse forwarder run; returns its verdict, its deny reason
    and its stderr."""
    script = (
        f"source .claude/init.sh\nPYTHON_CMD={python}\n"
        "validate_venv() { return 0; }\n"
        "_is_ci_environment() { return 1; }\n_is_ci_enforced() { return 1; }\n"
        f"_HOOKS_DAEMON_START_DEADLINE={deadline}\n{_FORWARDER_BODY}"
    )
    result = subprocess.run(
        [BASH, "-c", script],
        cwd=project,
        env=env,
        input=_stdin_text(_BASH_TOOL_INPUT),
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )
    verdict = _verdict(result)
    reason = _reason(json.loads(result.stdout)) if verdict == "deny" else ""
    return verdict, reason, result.stderr


def _await_only(project: Path, daemon_pid: int) -> list[int]:
    """Wait until the daemon is the one process left serving ``project``:
    every launcher has finished. Returns what is left when the wait ends."""
    end = time.monotonic() + 2 * Timeout.DAEMON_START_BUDGET_SEC
    left = find_all_daemon_processes(project_root=project)
    while left != [daemon_pid] and time.monotonic() < end:
        time.sleep(_POLL_SECONDS)
        left = find_all_daemon_processes(project_root=project)
    return left


def _slow_project(root: Path, in_container: bool) -> tuple[Path, Path, Path, dict[str, str]]:
    """A project whose daemon's init is slowed; returns it, the ``python``
    that starts it, the PID file and the environment a hook runs in."""
    project = _make_project(root / "p")
    subprocess.run(
        ["git", "-C", str(project), "remote", "add", "origin", "https://github.com/test/repo.git"],
        check=True,
        capture_output=True,
    )
    (project / ".claude" / "hooks-daemon.yaml").write_text(
        "version: '1.0'\n"
        "daemon:\n"
        "  idle_timeout_seconds: 600\n"
        "  self_install_mode: true\n"
        "  enforce_single_daemon_process: true\n"
        "handlers:\n"
        "  pre_tool_use: {}\n"
    )
    started_log = root / "started"
    python = _write_python_wrapper(root, started_log, in_container)
    pid_path = root / "d.pid"
    env = _script_env(
        root / "d.sock",
        extra_env={
            "CLAUDE_HOOKS_PID_PATH": str(pid_path),
            "CLAUDE_HOOKS_SOCKET_TIMEOUT": str(Timeout.SOCKET_CONNECT),
        },
    )
    return project, python, pid_path, env


def _assert_one_daemon_started_and_kept(root: Path, project: Path, pid_path: Path) -> None:
    """The PID file's daemon is the one process serving ``project``, and the
    only one that ever reached controller init."""
    daemon_pid = read_pid_file(str(pid_path))
    assert daemon_pid is not None
    assert _await_only(project, daemon_pid) == [daemon_pid]
    started = (root / "started").read_text().split()
    assert started == [str(daemon_pid)], started


@pytest.mark.parametrize("in_container", [True, False], ids=["container", "host"])
def test_two_concurrent_starts_start_one_daemon(root: Path, in_container: bool) -> None:
    """Ledger 00466 N232: two hooks each ran ``start`` at once. The second
    found no PID file and no live socket, so in a container its
    single-daemon enforcement stopped the first start's daemon while it was
    still initialising, and started another; elsewhere both initialised in
    full. The second start now waits on the first."""
    project, python, pid_path, env = _slow_project(root, in_container)
    launch = [str(python), "-m", "claude_code_hooks_daemon.daemon.cli"]
    launch += ["--project-root", str(project), "start"]
    starts = [
        subprocess.Popen(
            launch, cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for _ in range(2)
    ]
    outputs = [start.communicate(timeout=2 * Timeout.DAEMON_START_BUDGET_SEC) for start in starts]

    assert [start.returncode for start in starts] == [0, 0], outputs
    _assert_one_daemon_started_and_kept(root, project, pid_path)


@pytest.mark.parametrize("in_container", [True, False], ids=["container", "host"])
def test_a_retried_hook_waits_on_the_start_under_way(root: Path, in_container: bool) -> None:
    project, python, pid_path, env = _slow_project(root, in_container)

    first = _hook(project, env, python, _SHORT_DEADLINE)
    assert first[0] == "deny" and "starting" in first[1], first
    # The retry lands while the first daemon is still in its slowed init.
    retry = _hook(project, env, python, _SHORT_DEADLINE)
    assert retry[0] == "no-decision" or "starting" in retry[1], retry
    answered = _hook(project, env, python, Timeout.HOOK_START_DEADLINE_SEC)
    assert answered[0] == "no-decision", answered

    _assert_one_daemon_started_and_kept(root, project, pid_path)
