"""Plan 00466 N202 — ``start`` waits on a daemon whose controller init is slow.

Under load, controller init alone outlasted the parent's fixed 5 s wait, so
``restart`` printed "failed to start (no PID file created)" and exited 1 while
the daemon came up behind it. Loading the shared host to show that would
disturb every other run on it, so this throwaway daemon's controller init is
slowed instead: a ``sitecustomize`` on its ``PYTHONPATH`` sleeps before
``DaemonController.initialise`` for longer than that old wait.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.process_verification import find_all_daemon_processes
from claude_code_hooks_daemon.utils.safe_signal import stop_verified_daemon

_CLI = "claude_code_hooks_daemon.daemon.cli"

#: Longer than the 5 s the parent used to wait, shorter than the time a
#: daemon may make no progress before the wait gives up on it.
_INIT_DELAY_SECONDS = 7.0

#: Only stops a hung test: the start bounds itself well inside this.
_START_OUTER_BOUND = 4 * Timeout.DAEMON_START_BUDGET_SEC

_SLOW_INIT = f"""\
import time

from claude_code_hooks_daemon.daemon import controller

_initialise = controller.DaemonController.initialise


def _slowly(self, *args, **kwargs):
    time.sleep({_INIT_DELAY_SECONDS})
    return _initialise(self, *args, **kwargs)


controller.DaemonController.initialise = _slowly
"""


@pytest.fixture
def slow_project() -> Iterator[tuple[Path, dict[str, str]]]:
    """A throwaway project whose daemon's controller init is slow, on paths
    short enough for AF_UNIX."""
    root = Path(tempfile.mkdtemp(prefix="hd-slow-"))
    project = root / "project"
    project.mkdir()
    for argv in (
        ["git", "init"],
        ["git", "config", "user.email", "test@test.com"],
        ["git", "config", "user.name", "Test User"],
        ["git", "remote", "add", "origin", "https://github.com/test/repo.git"],
    ):
        subprocess.run(argv, cwd=project, check=True, capture_output=True)
    (project / ".claude").mkdir()
    (project / ".claude" / "hooks-daemon.yaml").write_text(
        "version: '1.0'\n"
        "daemon:\n"
        "  idle_timeout_seconds: 600\n"
        "  self_install_mode: true\n"
        "handlers:\n"
        "  pre_tool_use: {}\n"
    )
    customize = root / "customize"
    customize.mkdir()
    (customize / "sitecustomize.py").write_text(_SLOW_INIT)
    env = dict(os.environ)
    env["CLAUDE_HOOKS_SOCKET_PATH"] = str(root / "d.sock")
    env["CLAUDE_HOOKS_PID_PATH"] = str(root / "d.pid")
    env["CLAUDE_HOOKS_LOG_PATH"] = str(root / "d.log")
    try:
        yield project, env
    finally:
        # A start that gave up leaves a daemon still initialising, which has
        # no PID file for ``stop`` to find yet; its command line names the
        # project, so it is stopped through the verified path instead.
        for pid in find_all_daemon_processes(project_root=project):
            stop_verified_daemon(
                pid, project_root=project, grace_seconds=Timeout.PROCESS_DEATH_WAIT
            )
        shutil.rmtree(root)


def test_start_reports_a_daemon_that_outlasts_the_old_five_second_wait(
    slow_project: tuple[Path, dict[str, str]],
) -> None:
    project, env = slow_project
    slowed = dict(env)
    slowed["PYTHONPATH"] = os.pathsep.join(
        [str(project.parent / "customize"), env.get("PYTHONPATH", "")]
    )

    result = subprocess.run(
        [sys.executable, "-m", _CLI, "--project-root", str(project), "start"],
        env=slowed,
        capture_output=True,
        text=True,
        timeout=_START_OUTER_BOUND,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Daemon started successfully" in result.stdout
