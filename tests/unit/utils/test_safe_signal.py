"""Plan 00466 N59 — a nonzero signal goes only to a pid proven to be the intended process.

The positive cases use REAL children this test starts, so "the signal arrived"
is observed from the child's exit status rather than from a mock. Every
refusal is proven by the target surviving, or by the target never existing.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import psutil
import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.safe_signal import (
    DaemonStop,
    RefusedSignalTarget,
    signal_own_session_child,
    signal_verified_daemon,
    stop_verified_daemon,
    verified_daemon_process,
)

_SLEEP = "import time; time.sleep(600)"
#: Ignores SIGTERM, then says so on stdout so the test never signals it early.
_IGNORE_TERM = (
    "import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "print('ready', flush=True); time.sleep(600)"
)
_DAEMON_MODULE = "claude_code_hooks_daemon.daemon.cli"
#: Above Linux's default pid_max, so no process can have it.
_NONEXISTENT_PID = 2**22 + 7
_GRACE_SECONDS = 1.0


def _reap(child: subprocess.Popen[bytes]) -> None:
    if child.poll() is None:
        child.kill()
    child.wait(timeout=Timeout.PROCESS_SAMPLE)


@pytest.fixture
def children() -> Iterator[list[subprocess.Popen[bytes]]]:
    started: list[subprocess.Popen[bytes]] = []
    yield started
    for child in started:
        _reap(child)


def _spawn(
    children: list[subprocess.Popen[bytes]], *argv: str, new_session: bool = True
) -> subprocess.Popen[bytes]:
    child = subprocess.Popen([sys.executable, "-c", _SLEEP, *argv], start_new_session=new_session)
    children.append(child)
    return child


def _fake_daemon(
    children: list[subprocess.Popen[bytes]], project_root: Path
) -> subprocess.Popen[bytes]:
    """A real process whose command line is a daemon server for ``project_root``."""
    return _spawn(children, _DAEMON_MODULE, "--project-root", str(project_root), "start")


class TestAPidThatIsNotAPlainIntegerAboveOneIsRefused:
    @pytest.mark.parametrize("pid", [1, 0, -1, -4242])
    def test_init_and_group_aliases(self, pid: int, tmp_path: Path) -> None:
        with pytest.raises(RefusedSignalTarget):
            signal_verified_daemon(pid, signal.SIGTERM, project_root=tmp_path)

    def test_a_magicmock_pid_which_coerces_to_one(self, tmp_path: Path) -> None:
        with pytest.raises(RefusedSignalTarget):
            signal_verified_daemon(MagicMock().pid, signal.SIGTERM, project_root=tmp_path)

    def test_a_bool(self, tmp_path: Path) -> None:
        with pytest.raises(RefusedSignalTarget):
            signal_verified_daemon(True, signal.SIGTERM, project_root=tmp_path)

    def test_a_numeric_string(self, tmp_path: Path) -> None:
        with pytest.raises(RefusedSignalTarget):
            signal_verified_daemon("4242", signal.SIGTERM, project_root=tmp_path)


class TestThisProcessAndItsCallersAreRefused:
    def test_own_pid(self, tmp_path: Path) -> None:
        with pytest.raises(RefusedSignalTarget):
            signal_verified_daemon(os.getpid(), signal.SIGTERM, project_root=tmp_path)

    def test_parent_pid(self, tmp_path: Path) -> None:
        with pytest.raises(RefusedSignalTarget):
            signal_verified_daemon(os.getppid(), signal.SIGTERM, project_root=tmp_path)


class TestADaemonPidIsSignalledOnlyWhenItIsThisProjectsDaemon:
    def test_this_projects_daemon_is_signalled(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        daemon = _fake_daemon(children, tmp_path)

        signal_verified_daemon(daemon.pid, signal.SIGTERM, project_root=tmp_path)

        assert daemon.wait(timeout=Timeout.PROCESS_SAMPLE) == -signal.SIGTERM

    def test_a_daemon_of_another_project_root_is_refused(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        daemon = _fake_daemon(children, tmp_path / "other-project")

        with pytest.raises(RefusedSignalTarget, match="project root"):
            signal_verified_daemon(daemon.pid, signal.SIGTERM, project_root=tmp_path)
        assert daemon.poll() is None, "the other project's daemon must still be running"

    def test_a_stale_pid_file_naming_a_live_non_daemon_is_refused(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        bystander = _spawn(children)
        pid_file = tmp_path / "daemon-abc.pid"
        pid_file.write_text(str(bystander.pid), encoding="utf-8")

        stale_pid = int(pid_file.read_text(encoding="utf-8"))
        with pytest.raises(RefusedSignalTarget, match="not a daemon"):
            signal_verified_daemon(stale_pid, signal.SIGKILL, project_root=tmp_path)
        assert bystander.poll() is None, "the bystander must still be running"

    def test_a_pid_with_no_process_raises_process_lookup_error(self, tmp_path: Path) -> None:
        with pytest.raises(ProcessLookupError):
            signal_verified_daemon(_NONEXISTENT_PID, signal.SIGTERM, project_root=tmp_path)

    def test_the_verified_handle_is_this_projects_daemon(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        daemon = _fake_daemon(children, tmp_path)

        handle = verified_daemon_process(daemon.pid, project_root=tmp_path)

        assert handle.pid == daemon.pid


class TestStoppingADaemonTermsThenKillsOnlyThisProjectsDaemon:
    def test_a_daemon_that_honours_term_is_terminated(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        daemon = _fake_daemon(children, tmp_path)

        outcome = stop_verified_daemon(
            daemon.pid, project_root=tmp_path, grace_seconds=_GRACE_SECONDS
        )

        assert outcome is DaemonStop.TERMINATED

    def test_a_daemon_that_ignores_term_is_killed(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        daemon = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _IGNORE_TERM,
                _DAEMON_MODULE,
                "--project-root",
                str(tmp_path),
                "start",
            ],
            stdout=subprocess.PIPE,
            start_new_session=True,
        )
        children.append(daemon)
        assert daemon.stdout is not None
        assert daemon.stdout.readline() == b"ready\n"

        outcome = stop_verified_daemon(
            daemon.pid, project_root=tmp_path, grace_seconds=_GRACE_SECONDS
        )

        assert outcome is DaemonStop.KILLED

    def test_a_pid_with_no_process_is_already_gone(self, tmp_path: Path) -> None:
        outcome = stop_verified_daemon(
            _NONEXISTENT_PID, project_root=tmp_path, grace_seconds=_GRACE_SECONDS
        )

        assert outcome is DaemonStop.ALREADY_GONE

    def test_another_projects_daemon_is_refused_and_left_running(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        daemon = _fake_daemon(children, tmp_path / "other-project")

        with pytest.raises(RefusedSignalTarget):
            stop_verified_daemon(daemon.pid, project_root=tmp_path, grace_seconds=_GRACE_SECONDS)
        assert daemon.poll() is None

    def test_a_magicmock_pid_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(RefusedSignalTarget):
            stop_verified_daemon(
                MagicMock().pid, project_root=tmp_path, grace_seconds=_GRACE_SECONDS
            )

    def test_no_permission_to_signal_is_a_permission_error(
        self,
        tmp_path: Path,
        children: list[subprocess.Popen[bytes]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Tests run as root, which may signal anything, so the refusal the
        # kernel would give an unprivileged caller is raised here instead.
        daemon = _fake_daemon(children, tmp_path)

        def denied(process: psutil.Process) -> None:
            raise psutil.AccessDenied(process.pid)

        monkeypatch.setattr(psutil.Process, "terminate", denied)

        with pytest.raises(PermissionError):
            stop_verified_daemon(daemon.pid, project_root=tmp_path, grace_seconds=_GRACE_SECONDS)
        assert daemon.poll() is None


class TestAGroupIsSignalledOnlyWhenOurOwnChildLeadsIt:
    def test_a_child_started_in_its_own_session_is_killed_with_its_group(
        self, children: list[subprocess.Popen[bytes]]
    ) -> None:
        child = _spawn(children, new_session=True)

        signal_own_session_child(child, signal.SIGKILL)

        assert child.wait(timeout=Timeout.PROCESS_SAMPLE) == -signal.SIGKILL

    def test_a_magicmock_process_is_refused(self) -> None:
        with pytest.raises(RefusedSignalTarget):
            signal_own_session_child(MagicMock(), signal.SIGKILL)

    def test_a_mock_with_a_plain_pid_is_refused_by_its_poll_answer(self) -> None:
        mock = MagicMock(spec=subprocess.Popen)
        mock.pid = _NONEXISTENT_PID

        with pytest.raises(RefusedSignalTarget, match="poll"):
            signal_own_session_child(mock, signal.SIGKILL)

    def test_a_child_sharing_our_group_is_refused(
        self, children: list[subprocess.Popen[bytes]]
    ) -> None:
        child = _spawn(children, new_session=False)
        assert os.getpgid(child.pid) == os.getpgid(0)

        with pytest.raises(RefusedSignalTarget, match="does not lead"):
            signal_own_session_child(child, signal.SIGKILL)
        assert child.poll() is None, "our own group must not have been signalled"

    def test_a_child_that_has_already_exited_raises_process_lookup_error(
        self, children: list[subprocess.Popen[bytes]]
    ) -> None:
        child = _spawn(children, new_session=True)
        _reap(child)

        with pytest.raises(ProcessLookupError):
            signal_own_session_child(child, signal.SIGKILL)
