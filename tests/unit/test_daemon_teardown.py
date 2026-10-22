"""A test's daemon teardown treats a daemon already exiting as stopped (N268)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psutil
import pytest

from claude_code_hooks_daemon.utils.safe_signal import DaemonStop, RefusedSignalTarget
from tests import daemon_teardown

_PID = 4242
_DAEMON_CMDLINE = ["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"]


class _FakeProcess:
    """A process whose successive ``cmdline()`` answers are scripted; once the
    script is spent it is gone. ``zombie`` makes ``status()`` say so."""

    def __init__(self, cmdlines: list[list[str]], *, zombie: bool = False) -> None:
        self._cmdlines = list(cmdlines)
        self._zombie = zombie

    def status(self) -> str:
        return psutil.STATUS_ZOMBIE if self._zombie else psutil.STATUS_RUNNING

    def cmdline(self) -> list[str]:
        if not self._cmdlines:
            raise psutil.NoSuchProcess(_PID)
        return self._cmdlines.pop(0)


def _refuse(*_args: object, **_kwargs: object) -> DaemonStop:
    raise RefusedSignalTarget(f"pid {_PID} is not a daemon server: []")


@pytest.fixture
def refusing(monkeypatch: pytest.MonkeyPatch) -> Callable[[_FakeProcess | None], list[float]]:
    """Wire the helper to one pid whose verified stop is refused; the
    returned installer takes the process the pid now is (None: gone) and
    hands back the list of sleeps the helper asked for."""

    def install(process: _FakeProcess | None) -> list[float]:
        sleeps: list[float] = []
        monkeypatch.setattr(daemon_teardown, "find_all_daemon_processes", lambda **_: [_PID])
        monkeypatch.setattr(daemon_teardown, "stop_verified_daemon", _refuse)
        monkeypatch.setattr(daemon_teardown, "_sleep", sleeps.append)

        def make(pid: int) -> _FakeProcess:
            if process is None:
                raise psutil.NoSuchProcess(pid)
            return process

        monkeypatch.setattr(psutil, "Process", make)
        return sleeps

    return install


def test_a_verified_stop_is_used_for_each_daemon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stopped: list[int] = []

    def stop(pid: int, **_: object) -> DaemonStop:
        stopped.append(pid)
        return DaemonStop.TERMINATED

    monkeypatch.setattr(daemon_teardown, "find_all_daemon_processes", lambda **_: [1, 2])
    monkeypatch.setattr(daemon_teardown, "stop_verified_daemon", stop)

    daemon_teardown.stop_daemons_of(tmp_path, grace_seconds=1)

    assert stopped == [1, 2]


def _scans(monkeypatch: pytest.MonkeyPatch, answers: list[list[int]]) -> list[int]:
    """Wire the helper to successive scans (the last one repeats); returns the
    list the verified stop appends each pid it is asked to stop to."""
    stopped: list[int] = []
    remaining = list(answers)

    def scan(**_: object) -> list[int]:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    def stop(pid: int, **_: object) -> DaemonStop:
        stopped.append(pid)
        return DaemonStop.TERMINATED

    monkeypatch.setattr(daemon_teardown, "find_all_daemon_processes", scan)
    monkeypatch.setattr(daemon_teardown, "stop_verified_daemon", stop)
    return stopped


def test_a_daemon_forked_by_a_launcher_as_it_is_stopped_is_stopped_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """N527: a launcher stopped mid-start has already forked the daemon that
    the first scan could not see; it would write into the tree after teardown."""
    launcher, forked_daemon = 10, 11
    stopped = _scans(monkeypatch, [[launcher], [forked_daemon], []])

    daemon_teardown.stop_daemons_of(tmp_path, grace_seconds=1)

    assert stopped == [launcher, forked_daemon]


def test_a_pid_already_stopped_is_not_stopped_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stopped = _scans(monkeypatch, [[10], [10, 11], [10]])

    daemon_teardown.stop_daemons_of(tmp_path, grace_seconds=1)

    assert stopped == [10, 11]


def test_daemons_that_keep_appearing_are_reported_not_chased_for_ever(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    answers = [[pid] for pid in range(1, daemon_teardown._POLLS + 5)]
    _scans(monkeypatch, answers)

    with pytest.raises(RuntimeError, match="kept appearing"):
        daemon_teardown.stop_daemons_of(tmp_path, grace_seconds=1)


def test_a_pid_gone_by_the_time_of_the_refusal_counts_as_stopped(
    refusing: Callable[[_FakeProcess | None], list[float]], tmp_path: Path
) -> None:
    refusing(None)

    daemon_teardown.stop_daemons_of(tmp_path, grace_seconds=1)


def test_a_zombie_counts_as_stopped(
    refusing: Callable[[_FakeProcess | None], list[float]], tmp_path: Path
) -> None:
    refusing(_FakeProcess([[]], zombie=True))

    daemon_teardown.stop_daemons_of(tmp_path, grace_seconds=1)


def test_an_empty_command_line_that_then_vanishes_counts_as_stopped(
    refusing: Callable[[_FakeProcess | None], list[float]], tmp_path: Path
) -> None:
    sleeps = refusing(_FakeProcess([[], [], []]))

    daemon_teardown.stop_daemons_of(tmp_path, grace_seconds=1)

    assert sleeps, "the helper must give an exiting process a moment"


def test_an_empty_command_line_that_stays_empty_counts_as_stopped(
    refusing: Callable[[_FakeProcess | None], list[float]], tmp_path: Path
) -> None:
    refusing(_FakeProcess([[]] * 10_000))

    daemon_teardown.stop_daemons_of(tmp_path, grace_seconds=1)


def test_a_live_process_that_is_not_a_daemon_is_still_refused(
    refusing: Callable[[_FakeProcess | None], list[float]], tmp_path: Path
) -> None:
    refusing(_FakeProcess([["sleep", "100"]] * 3))

    with pytest.raises(RefusedSignalTarget):
        daemon_teardown.stop_daemons_of(tmp_path, grace_seconds=1)


def test_an_empty_command_line_that_turns_into_a_non_daemon_is_refused(
    refusing: Callable[[_FakeProcess | None], list[float]], tmp_path: Path
) -> None:
    refusing(_FakeProcess([[], ["sleep", "100"]]))

    with pytest.raises(RefusedSignalTarget):
        daemon_teardown.stop_daemons_of(tmp_path, grace_seconds=1)
