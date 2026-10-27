"""Plan 00529 Task 2c (ruling task 4): the detached session-start relay repair.

When ``relay_binary_checker`` finds the configured relay binary unusable, it
starts the ``transport on`` provisioning (``ensure_relay_binary`` plus forwarder
regeneration, without the toggle) detached from the hook, once per cause: a
state file keyed by binary path, defect and daemon version records the attempt,
and a lock keeps two repairs from building at once. A failed repair is
recorded and reported, never swallowed.
"""

from __future__ import annotations

import fcntl
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.install import relay_repair
from claude_code_hooks_daemon.install.background_sync import (
    SyncRecord,
    SyncStatus,
    read_state_file,
)
from claude_code_hooks_daemon.install.relay_repair import (
    REPAIR_STATE_DIR_NAME,
    RepairNotice,
    SpawnFn,
    cause_key,
    repair_lock_path,
    repair_log_path,
    repair_state_path,
    run_relay_repair,
    spawn_detached,
    start_relay_repair,
)
from claude_code_hooks_daemon.install.transport_toggle import RelayProvision

_VERSION = "3.99.0"
_DEFECT = "missing"
# How long the lock test watches a repair stay blocked behind a held lock.
_STILL_BLOCKED_OBSERVATION_SECONDS = Timeout.SOCKET_LIVENESS_PROBE_SEC


_WAIT_DEADLINE_SECONDS = 10.0
_WAIT_POLL_SECONDS = 0.01


class _Spawner:
    """Records each detached spawn instead of starting a process."""

    # A live pid: the claim records it, and a dead one would read as failed.
    PID = os.getpid()

    def __init__(self, error: OSError | None = None) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self.error = error

    def __call__(self, argv: list[str], log: Path) -> int:
        self.calls.append((argv, log))
        if self.error is not None:
            raise self.error
        return self.PID


class _FinishingSpawner(_Spawner):
    """A child that records its result before the spawn call even returns."""

    def __call__(self, argv: list[str], log: Path) -> int:
        state = Path(argv[argv.index("--state") + 1])
        state.write_text(f"status=synced\npid={self.PID}\ndetail=done\n")
        return super().__call__(argv, log)


def _wait_for(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + _WAIT_DEADLINE_SECONDS
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached before the deadline")
        time.sleep(_WAIT_POLL_SECONDS)


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _start(tmp_path: Path, spawner: SpawnFn, *, defect: str = _DEFECT) -> RepairNotice:
    return start_relay_repair(
        tmp_path / "project",
        tmp_path / "bin" / "hooks-relay",
        defect,
        untracked_dir=tmp_path / "untracked",
        version=_VERSION,
        spawn_fn=spawner,
    )


class TestCauseKey:
    def test_stable_for_the_same_cause(self, tmp_path: Path) -> None:
        binary = tmp_path / "hooks-relay"

        assert cause_key(binary, _DEFECT, _VERSION) == cause_key(binary, _DEFECT, _VERSION)

    @pytest.mark.parametrize(
        ("binary", "defect", "version"),
        [
            ("other-relay", _DEFECT, _VERSION),
            ("hooks-relay", "not executable", _VERSION),
            ("hooks-relay", _DEFECT, "3.99.1"),
        ],
    )
    def test_a_different_binary_defect_or_version_is_a_different_cause(
        self, tmp_path: Path, binary: str, defect: str, version: str
    ) -> None:
        base = cause_key(tmp_path / "hooks-relay", _DEFECT, _VERSION)

        assert cause_key(tmp_path / binary, defect, version) != base

    def test_files_live_under_the_repair_state_dir(self, tmp_path: Path) -> None:
        key = cause_key(tmp_path / "hooks-relay", _DEFECT, _VERSION)

        assert repair_state_path(tmp_path, key).parent == tmp_path / REPAIR_STATE_DIR_NAME
        assert repair_log_path(tmp_path, key).parent == tmp_path / REPAIR_STATE_DIR_NAME
        assert repair_lock_path(tmp_path).parent == tmp_path / REPAIR_STATE_DIR_NAME


class TestStartRelayRepair:
    def test_first_call_spawns_the_repair_module_detached(self, tmp_path: Path) -> None:
        spawner = _Spawner()

        notice = _start(tmp_path, spawner)

        assert notice.started is True
        assert notice.failure is None
        assert notice.record is None
        ((argv, log),) = spawner.calls
        assert argv[:3] == [sys.executable, "-m", "claude_code_hooks_daemon.install.relay_repair"]
        assert str(tmp_path / "project") in argv
        assert str(tmp_path / "bin" / "hooks-relay") in argv
        assert str(notice.state_path) in argv
        assert log == notice.log_path

    def test_the_claim_is_recorded_as_running_before_the_child_starts(self, tmp_path: Path) -> None:
        notice = _start(tmp_path, _Spawner())

        record = read_state_file(notice.state_path, notice.log_path)
        assert record is not None
        assert record.status is SyncStatus.RUNNING

    def test_the_spawned_pid_is_recorded_at_once(self, tmp_path: Path) -> None:
        """The child may die before it records its own pid; the claim must carry it anyway."""
        notice = _start(tmp_path, _Spawner())

        text = notice.state_path.read_text()
        assert "status=running" in text
        assert f"pid={_Spawner.PID}" in text

    def test_a_result_the_child_already_recorded_is_not_overwritten(self, tmp_path: Path) -> None:
        """A child fast enough to finish before the parent records its pid keeps its result."""
        notice = _start(tmp_path, _FinishingSpawner())

        text = notice.state_path.read_text()
        assert "status=synced" in text
        assert "status=running" not in text

    def test_a_pid_that_cannot_be_recorded_is_reported_with_the_start(self, tmp_path: Path) -> None:
        """The repair is running; its missing pid is reported, not only logged."""

        def spawn_and_lose_state(argv: list[str], log: Path) -> int:
            Path(argv[argv.index("--state") + 1]).unlink()
            return _Spawner.PID

        notice = _start(tmp_path, spawn_and_lose_state)

        assert notice.started is True
        assert notice.failure is not None
        assert f"pid {_Spawner.PID}" in notice.failure
        assert "could not be recorded" in notice.failure

    def test_a_child_that_dies_before_recording_its_pid_reads_as_failed(
        self, tmp_path: Path
    ) -> None:
        pids: list[int] = []

        def spawn_false(argv: list[str], log: Path) -> int:
            pid = spawn_detached(["/bin/false"], log)
            pids.append(pid)
            return pid

        notice = _start(tmp_path, spawn_false)

        def failed() -> bool:
            record = read_state_file(notice.state_path, notice.log_path)
            return record is not None and record.status is SyncStatus.FAILED

        _wait_for(failed)
        record = read_state_file(notice.state_path, notice.log_path)
        assert record is not None and record.pid == pids[0]

    def test_the_same_cause_is_attempted_once(self, tmp_path: Path) -> None:
        spawner = _Spawner()
        _start(tmp_path, spawner)

        second = _start(tmp_path, spawner)

        assert len(spawner.calls) == 1
        assert second.started is False
        assert second.record is not None
        assert second.record.status is SyncStatus.RUNNING

    def test_a_new_cause_is_attempted_again(self, tmp_path: Path) -> None:
        spawner = _Spawner()
        _start(tmp_path, spawner)

        again = _start(tmp_path, spawner, defect="not executable")

        assert again.started is True
        assert len(spawner.calls) == 2

    def test_a_failed_spawn_is_reported_and_recorded(self, tmp_path: Path) -> None:
        notice = _start(tmp_path, _Spawner(error=OSError(13, "Permission denied")))

        assert notice.started is False
        assert notice.failure is not None
        assert "Permission denied" in notice.failure
        record = read_state_file(notice.state_path, notice.log_path)
        assert record is not None
        assert record.status is SyncStatus.FAILED
        assert "Permission denied" in record.detail

    def test_a_failed_spawn_is_not_retried_for_the_same_cause(self, tmp_path: Path) -> None:
        _start(tmp_path, _Spawner(error=OSError(13, "Permission denied")))
        spawner = _Spawner()

        second = _start(tmp_path, spawner)

        assert spawner.calls == []
        assert second.record is not None
        assert second.record.status is SyncStatus.FAILED

    def test_an_uncreatable_state_dir_is_reported_not_raised(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        untracked.write_text("a file where the directory should be")
        spawner = _Spawner()

        notice = start_relay_repair(
            tmp_path,
            tmp_path / "hooks-relay",
            _DEFECT,
            untracked_dir=untracked,
            version=_VERSION,
            spawn_fn=spawner,
        )

        assert notice.started is False
        assert notice.failure is not None
        assert spawner.calls == []


class _Repair:
    """Injected provisioning steps that record what ran."""

    def __init__(
        self,
        *,
        provision: RelayProvision | None = None,
        defects: list[str | None] | None = None,
        regenerate_error: Exception | None = None,
    ) -> None:
        self.provision_result = provision if provision is not None else RelayProvision()
        self.defects = defects if defects is not None else [_DEFECT, None]
        self.regenerate_error = regenerate_error
        self.provisioned = 0
        self.regenerated = 0

    def provision(self) -> RelayProvision:
        self.provisioned += 1
        return self.provision_result

    def regenerate(self) -> list[str]:
        self.regenerated += 1
        if self.regenerate_error is not None:
            raise self.regenerate_error
        return ["pre-tool-use"]

    def defect(self, binary: Path) -> str | None:
        return self.defects.pop(0) if len(self.defects) > 1 else self.defects[0]


def _claimed_state(tmp_path: Path) -> Path:
    state = repair_state_path(tmp_path / "untracked", "k")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("status=running\n")
    return state


def _run(tmp_path: Path, repair: _Repair) -> tuple[int, Path]:
    state = _claimed_state(tmp_path)
    code = run_relay_repair(
        tmp_path / "hooks-relay",
        state,
        repair_lock_path(tmp_path / "untracked"),
        provision_fn=repair.provision,
        regenerate_fn=repair.regenerate,
        defect_fn=repair.defect,
    )
    return code, state


def _record(state: Path) -> SyncRecord:
    record = read_state_file(state, state.with_suffix(".log"))
    assert record is not None
    return record


class TestRunRelayRepair:
    def test_success_provisions_regenerates_and_records_synced(self, tmp_path: Path) -> None:
        repair = _Repair(provision=RelayProvision(route="build", binary="/x/hooks-relay"))

        code, state = _run(tmp_path, repair)

        assert code == 0
        assert (repair.provisioned, repair.regenerated) == (1, 1)
        record = _record(state)
        assert record.status is SyncStatus.SYNCED
        assert "build" in record.detail
        assert "pre-tool-use" in record.detail

    def test_records_its_own_pid_while_running(self, tmp_path: Path) -> None:
        seen: list[str] = []
        repair = _Repair()
        state = _claimed_state(tmp_path)

        def provision() -> RelayProvision:
            seen.append(state.read_text())
            return RelayProvision()

        run_relay_repair(
            tmp_path / "hooks-relay",
            state,
            repair_lock_path(tmp_path / "untracked"),
            provision_fn=provision,
            regenerate_fn=repair.regenerate,
            defect_fn=repair.defect,
        )

        assert f"pid={os.getpid()}" in seen[0]
        assert "status=running" in seen[0]

    def test_a_provisioning_failure_is_recorded_failed(self, tmp_path: Path) -> None:
        repair = _Repair(provision=RelayProvision(failure="relay-binary: no rustc on PATH"))

        code, state = _run(tmp_path, repair)

        assert code != 0
        assert repair.regenerated == 0
        record = _record(state)
        assert record.status is SyncStatus.FAILED
        assert "no rustc on PATH" in record.detail

    def test_a_binary_still_unusable_afterwards_is_failed(self, tmp_path: Path) -> None:
        repair = _Repair(defects=[_DEFECT, _DEFECT])

        code, state = _run(tmp_path, repair)

        assert code != 0
        record = _record(state)
        assert record.status is SyncStatus.FAILED
        assert _DEFECT in record.detail

    def test_an_exception_is_recorded_failed_and_reraised(self, tmp_path: Path) -> None:
        repair = _Repair(regenerate_error=PermissionError("hooks dir is read-only"))

        with pytest.raises(PermissionError):
            _run(tmp_path, repair)

        record = _record(repair_state_path(tmp_path / "untracked", "k"))
        assert record.status is SyncStatus.FAILED
        assert "hooks dir is read-only" in record.detail

    def test_a_binary_repaired_meanwhile_is_left_alone(self, tmp_path: Path) -> None:
        repair = _Repair(defects=[None])

        code, state = _run(tmp_path, repair)

        assert code == 0
        assert repair.provisioned == 0
        assert _record(state).status is SyncStatus.SYNCED

    def test_waits_for_the_lock_another_repair_holds(self, tmp_path: Path) -> None:
        lock = repair_lock_path(tmp_path / "untracked")
        lock.parent.mkdir(parents=True)
        repair = _Repair()
        result: list[int] = []
        with lock.open("w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            worker = threading.Thread(target=lambda: result.append(_run(tmp_path, repair)[0]))
            worker.start()
            worker.join(timeout=_STILL_BLOCKED_OBSERVATION_SECONDS)
            assert worker.is_alive()
            assert repair.provisioned == 0
            fcntl.flock(held, fcntl.LOCK_UN)
        worker.join(timeout=Timeout.FILE_LOCK)

        assert result == [0]
        assert repair.provisioned == 1


class TestSpawnDetached:
    def test_runs_in_its_own_session_with_output_in_the_log(self, tmp_path: Path) -> None:
        log = tmp_path / "repair.log"
        program = (
            "import os, sys; "
            "print(os.getsid(0) == os.getpid(), sys.stdin.read() == ''); "
            "print('to-stderr', file=sys.stderr)"
        )

        pid = spawn_detached([sys.executable, "-c", program], log)
        _wait_for(lambda: _gone(pid))

        text = log.read_text()
        assert "True True" in text
        assert "to-stderr" in text

    def test_the_child_is_reaped_when_it_exits(self, tmp_path: Path) -> None:
        """The caller never waits, so an unreaped child would stay a zombie that looks alive."""
        pid = spawn_detached(["/bin/true"], tmp_path / "repair.log")

        _wait_for(lambda: _gone(pid))

        with pytest.raises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)

    def test_a_missing_program_raises(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            spawn_detached([str(tmp_path / "no-such-program")], tmp_path / "repair.log")

    def test_works_where_posix_spawn_has_no_setsid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """uv-managed CPython builds raise for ``posix_spawn(setsid=True)`` (ledger 00474 N541)."""
        real_spawn = os.posix_spawn

        def no_setsid(*args: Any, **kwargs: Any) -> int:
            if kwargs.get("setsid"):
                raise NotImplementedError("posix_spawn: setsid unavailable on this platform")
            return real_spawn(*args, **kwargs)

        monkeypatch.setattr(os, "posix_spawn", no_setsid)
        log = tmp_path / "repair.log"

        pid = spawn_detached(
            [sys.executable, "-c", "import os; print(os.getsid(0) == os.getpid())"], log
        )
        _wait_for(lambda: _gone(pid))

        assert "True" in log.read_text()


class TestMain:
    def test_wires_the_transport_on_steps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, object] = {}

        def fake_run(binary: Path, state: Path, lock: Path, **steps: object) -> int:
            seen.update(binary=binary, state=state, lock=lock, steps=sorted(steps))
            return 7

        monkeypatch.setattr(relay_repair, "run_relay_repair", fake_run)
        state = tmp_path / REPAIR_STATE_DIR_NAME / "k.state"

        code = relay_repair.main(
            [
                "--project-root",
                str(tmp_path),
                "--binary",
                str(tmp_path / "hooks-relay"),
                "--state",
                str(state),
            ]
        )

        assert code == 7
        assert seen["binary"] == tmp_path / "hooks-relay"
        assert seen["state"] == state
        assert seen["lock"] == repair_lock_path(tmp_path)
        assert seen["steps"] == ["defect_fn", "provision_fn", "regenerate_fn"]
