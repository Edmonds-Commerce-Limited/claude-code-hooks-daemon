"""Plan 00608: a repair the daemon started is stopped with the daemon.

The daemon-start repair is a child of the daemon, so the daemon owns it: a
stop ends it (its whole process group, so a build it runs goes too), waits for
it, and leaves no claim that says it is still running. Nothing may write under
the project after the stop returns. The SessionStart repair is not owned: its
parent is a hook process that exits at once, so it stays detached by design.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psutil
import pytest

from claude_code_hooks_daemon.install import relay_repair
from claude_code_hooks_daemon.install.background_sync import SyncStatus, read_state_file
from claude_code_hooks_daemon.install.relay_repair import (
    spawn_detached,
    spawn_owned,
    stop_owned_repairs,
)
from claude_code_hooks_daemon.utils.safe_signal import signal_own_session_child
from tests.load_scaling import scaled_seconds

_DEADLINE_SECONDS = 10.0
_POLL_SECONDS = 0.02

_SLEEPER = "import time; time.sleep(120)"
_IGNORES_TERM = (
    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"
)
_WRITER = (
    "import sys, time\n"
    "while True:\n"
    "    with open(sys.argv[1], 'a') as f:\n"
    "        f.write('x')\n"
    "    time.sleep(0.01)\n"
)
_SPAWNS_GRANDCHILD = (
    "import subprocess, sys, time\n"
    "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "open(sys.argv[1], 'w').write(str(g.pid))\n"
    "time.sleep(120)\n"
)


@pytest.fixture(autouse=True)
def _no_repairs_left() -> Iterator[None]:
    """Each test starts and ends with no owned repair, whatever it did."""
    stop_owned_repairs()
    yield
    stop_owned_repairs()


def _argv(script: str, state: Path, *extra: str) -> list[str]:
    return [sys.executable, "-c", script, *extra, "--state", str(state)]


def _wait_for(predicate: object) -> None:
    assert callable(predicate)
    deadline = time.monotonic() + _DEADLINE_SECONDS
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(_POLL_SECONDS)


def _gone(pid: int) -> bool:
    return not psutil.pid_exists(pid)


class TestStopOwnedRepairs:
    def test_nothing_owned_stops_nothing(self) -> None:
        assert stop_owned_repairs() == []

    def test_the_owned_child_is_gone_when_stop_returns(self, tmp_path: Path) -> None:
        pid = spawn_owned(_argv(_SLEEPER, tmp_path / "s.state"), tmp_path / "s.log")
        assert psutil.pid_exists(pid)

        assert stop_owned_repairs() == [pid]

        assert _gone(pid)

    def test_a_child_that_ignores_sigterm_is_killed_within_the_bound(self, tmp_path: Path) -> None:
        pid = spawn_owned(_argv(_IGNORES_TERM, tmp_path / "s.state"), tmp_path / "s.log")
        time.sleep(0.3)  # let the child install its handler

        started = time.monotonic()
        stop_owned_repairs()

        assert _gone(pid)
        assert time.monotonic() - started < scaled_seconds(5.0)

    def test_a_process_the_child_started_is_ended_too(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "grandchild.pid"
        spawn_owned(_argv(_SPAWNS_GRANDCHILD, tmp_path / "s.state", str(pid_file)), tmp_path / "l")
        _wait_for(lambda: pid_file.exists() and pid_file.read_text() != "")
        grandchild = int(pid_file.read_text())
        assert psutil.pid_exists(grandchild)

        stop_owned_repairs()

        _wait_for(lambda: _gone(grandchild))

    def test_nothing_is_written_after_stop_returns(self, tmp_path: Path) -> None:
        written = tmp_path / "written"
        spawn_owned(_argv(_WRITER, tmp_path / "s.state", str(written)), tmp_path / "l")
        _wait_for(written.exists)

        stop_owned_repairs()
        size = written.stat().st_size
        time.sleep(0.2)

        assert written.stat().st_size == size

    def test_a_claim_still_running_is_withdrawn_so_the_next_start_retries(
        self, tmp_path: Path
    ) -> None:
        state = tmp_path / "s.state"
        state.write_text("status=running\ndetail=repairing\n")
        spawn_owned(_argv(_SLEEPER, state), tmp_path / "s.log")

        stop_owned_repairs()

        assert not state.exists()

    def test_a_recorded_result_is_kept(self, tmp_path: Path) -> None:
        state = tmp_path / "s.state"
        state.write_text("status=failed\ndetail=no network\n")
        spawn_owned(_argv(_SLEEPER, state), tmp_path / "s.log")

        stop_owned_repairs()

        record = read_state_file(state, tmp_path / "s.log")
        assert record is not None
        assert record.status is SyncStatus.FAILED

    def test_a_child_that_already_exited_is_not_signalled(self, tmp_path: Path) -> None:
        spawn_owned(
            [sys.executable, "-c", "pass", "--state", str(tmp_path / "s.state")], tmp_path / "l"
        )
        _wait_for(lambda: relay_repair.owned_repair_pids() == [])

        assert stop_owned_repairs() == []

    def test_a_second_stop_finds_nothing(self, tmp_path: Path) -> None:
        spawn_owned(_argv(_SLEEPER, tmp_path / "s.state"), tmp_path / "s.log")
        stop_owned_repairs()

        assert stop_owned_repairs() == []


class TestNoSpawnAfterStop:
    """N-18: a start that passed the shutdown check must not spawn once stop began."""

    def test_spawn_owned_refuses_after_stop(self, tmp_path: Path) -> None:
        stop_owned_repairs()

        with pytest.raises(OSError):
            spawn_owned(_argv(_SLEEPER, tmp_path / "s.state"), tmp_path / "s.log")

        assert relay_repair.owned_repair_pids() == []

    def test_a_refused_start_withdraws_its_claim_so_the_next_start_retries(
        self, tmp_path: Path
    ) -> None:
        stop_owned_repairs()
        untracked = tmp_path / "untracked"
        binary = tmp_path / "relay"

        notice = relay_repair.start_relay_repair(
            tmp_path,
            binary,
            "missing",
            untracked_dir=untracked,
            version="1.0",
            spawn_fn=spawn_owned,
        )

        assert not notice.started
        assert notice.failure is not None
        assert not notice.state.exists()


class TestSessionStartRepairStaysDetached:
    def test_spawn_detached_is_not_owned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The hook that starts it exits at once; a stop must not end it."""
        spawned: list[subprocess.Popen[Any]] = []
        real_popen = subprocess.Popen

        def recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
            child: subprocess.Popen[Any] = real_popen(*args, **kwargs)
            spawned.append(child)
            return child

        monkeypatch.setattr(subprocess, "Popen", recording_popen)
        pid = spawn_detached(_argv(_SLEEPER, tmp_path / "s.state"), tmp_path / "s.log")
        try:
            assert stop_owned_repairs() == []
            assert psutil.pid_exists(pid)
        finally:
            signal_own_session_child(spawned[0], signal.SIGKILL)

    def test_owned_registry_is_a_module_level_view(self) -> None:
        assert relay_repair.owned_repair_pids() == []
