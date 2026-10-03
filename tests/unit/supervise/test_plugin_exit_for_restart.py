"""Plan 00487 Task 1.3b -- ExitForRestart.

A worker half returning ``ExitForRestart`` asks the session to end so the ccy
launcher can relaunch it (on a fresh image) with ``--resume <id>``. The host
refuses when the session id is ambiguous; otherwise it types ``/exit`` through
the existing injection path, holds every other injection until the child
exits (bounded -- a child that ignores ``/exit`` is abandoned and the session
carries on), writes a small request file, and exits with a dedicated status.
"""

from __future__ import annotations

import json
import os
import stat
from typing import TYPE_CHECKING, Any

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_mod = load_supervisor_module()

_SESSION = "sess-restart-1"
_NOW = 70_000.0


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class _Writer:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def __call__(self, data: bytes) -> None:
        self.chunks.append(data)

    @property
    def text(self) -> str:
        return b"".join(self.chunks).decode()


def _coordinator(tmp_path: Path, clock: _Clock | None = None, wait: float = 30.0) -> Any:
    clock = clock or _Clock()
    return _mod.RestartCoordinator(
        state_path=tmp_path / "state" / "restart-request.json",
        wait_seconds=wait,
        monotonic=clock,
        wall_clock=lambda: _NOW,
        sleep=lambda seconds: None,
    )


def _request(
    coordinator: Any,
    writer: _Writer,
    *,
    sessions: frozenset[str] = frozenset({_SESSION}),
    dry_run: bool = False,
    log: Any = None,
    machine: Any = None,
) -> bool:
    return bool(
        coordinator.request(
            "max-age",
            "session is 3 days old",
            session_ids=sessions,
            machine=machine or _mod.CompactStateMachine(_mod.CompactPolicy()),
            write_master=writer,
            log=log,
            dry_run=dry_run,
        )
    )


class TestStatusConstant:
    def test_the_exit_status_is_dedicated_and_documented_in_one_place(self) -> None:
        status = _mod.EXIT_STATUS_RESTART_REQUESTED
        assert isinstance(status, int)
        # Not success, not a generic failure, not a usage error, not the exec
        # failure status, and not a signal death (128 + n).
        assert status not in {0, 1, 2, 126, 127}
        assert status < 128


class TestRequest:
    def test_types_exit_through_the_injection_path_and_goes_pending(self, tmp_path: Path) -> None:
        coordinator, writer = _coordinator(tmp_path), _Writer()
        assert _request(coordinator, writer)
        assert coordinator.pending
        assert "/exit" in writer.text
        assert writer.text.endswith("\r")
        assert writer.text.startswith(_mod._PASTE_START)

    def test_the_exit_line_is_tracked_as_an_unconfirmed_own_line(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        _request(_coordinator(tmp_path), _Writer(), machine=machine)
        assert machine.own_line_pending

    def test_a_second_request_while_pending_types_nothing(self, tmp_path: Path) -> None:
        coordinator, writer = _coordinator(tmp_path), _Writer()
        _request(coordinator, writer)
        before = len(writer.chunks)
        assert not _request(coordinator, writer)
        assert len(writer.chunks) == before

    def test_an_ambiguous_session_id_is_refused_before_anything_is_typed(
        self, tmp_path: Path
    ) -> None:
        for sessions in (frozenset(), frozenset({"a", "b"})):
            coordinator, writer = _coordinator(tmp_path), _Writer()
            assert not _request(coordinator, writer, sessions=sessions)
            assert writer.chunks == []
            assert not coordinator.pending

    def test_a_refusal_is_logged(self, tmp_path: Path) -> None:
        log = _mod.DecisionLog(tmp_path / "decision.log")
        _request(_coordinator(tmp_path), _Writer(), sessions=frozenset({"a", "b"}), log=log)
        assert "refused" in (tmp_path / "decision.log").read_text()

    def test_dry_run_never_exits(self, tmp_path: Path) -> None:
        coordinator, writer = _coordinator(tmp_path), _Writer()
        log = _mod.DecisionLog(tmp_path / "decision.log")
        assert not _request(coordinator, writer, dry_run=True, log=log)
        assert writer.chunks == []
        assert not coordinator.pending
        assert "dry-run" in (tmp_path / "decision.log").read_text()


class TestHoldAndAbandon:
    def test_the_hold_is_bounded(self, tmp_path: Path) -> None:
        clock = _Clock()
        coordinator = _coordinator(tmp_path, clock, wait=30.0)
        _request(coordinator, _Writer())
        clock.now += 29.0
        assert not coordinator.expired()
        clock.now += 2.0
        assert coordinator.expired()

    def test_nothing_pending_never_expires(self, tmp_path: Path) -> None:
        assert not _coordinator(tmp_path).expired()

    def test_abandoning_releases_the_hold_and_writes_no_request(self, tmp_path: Path) -> None:
        coordinator = _coordinator(tmp_path)
        log = _mod.DecisionLog(tmp_path / "decision.log")
        _request(coordinator, _Writer())
        coordinator.abandon(log)
        assert not coordinator.pending
        assert "abandon" in (tmp_path / "decision.log").read_text()
        assert coordinator.finish(3, log) == 3
        assert not (tmp_path / "state" / "restart-request.json").exists()


class TestFinish:
    def test_without_a_request_the_childs_status_is_returned(self, tmp_path: Path) -> None:
        assert _coordinator(tmp_path).finish(7, None) == 7

    def test_a_pending_request_writes_the_file_and_returns_the_dedicated_status(
        self, tmp_path: Path
    ) -> None:
        coordinator = _coordinator(tmp_path)
        _request(coordinator, _Writer())
        assert coordinator.finish(0, None) == _mod.EXIT_STATUS_RESTART_REQUESTED
        path = tmp_path / "state" / "restart-request.json"
        assert json.loads(path.read_text()) == {
            "session_id": _SESSION,
            "reason": "session is 3 days old",
            "plugin": "max-age",
            "requested_at": _NOW,
        }
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_the_request_is_consumed_by_finishing(self, tmp_path: Path) -> None:
        coordinator = _coordinator(tmp_path)
        _request(coordinator, _Writer())
        coordinator.finish(0, None)
        assert not coordinator.pending
        assert coordinator.finish(4, None) == 4

    def test_an_unwritable_state_dir_falls_back_to_the_childs_status(self, tmp_path: Path) -> None:
        blocker = tmp_path / "state"
        blocker.write_text("a file where the directory should be")
        coordinator = _coordinator(tmp_path)
        log = _mod.DecisionLog(tmp_path / "decision.log")
        _request(coordinator, _Writer())
        assert coordinator.finish(5, log) == 5
        assert "could not write" in (tmp_path / "decision.log").read_text()

    def test_the_default_location_is_under_the_ccy_state_directory(self) -> None:
        assert _mod._restart_request_path() == _mod._ccy_state_dir() / "restart-request.json"
        assert _mod._ccy_state_dir().parent == _mod._SELF_PATH.parent


# -- supervise(): the whole path over a real PTY -----------------------------

# A child that records every byte it is sent, exits cleanly on `/exit` and
# otherwise waits for `linger` seconds before exiting on its own.
_CHILD = r"""
import os, sys, time, select
log = open(sys.argv[1], "ab", buffering=0)
deadline = time.time() + float(sys.argv[2])
while time.time() < deadline:
    ready, _, _ = select.select([0], [], [], 0.05)
    if not ready:
        continue
    data = os.read(0, 4096)
    log.write(data)
    if sys.argv[3].encode() in data:
        sys.exit(0)
sys.exit(int(sys.argv[4]))
"""


def _run_supervise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    decider: Any,
    sessions: frozenset[str] = frozenset({_SESSION}),
    linger: float = 5.0,
    exit_marker: str = "/exit",
    own_exit: int = 3,
    wait_seconds: float = 30.0,
    dry_run: bool = False,
) -> tuple[int, Path]:
    monkeypatch.setattr(_mod, "cached_own_session_ids", lambda *args, **kwargs: sessions)
    received = tmp_path / "received.bin"
    coordinator = _mod.RestartCoordinator(
        state_path=tmp_path / "state" / "restart-request.json", wait_seconds=wait_seconds
    )
    stdin_fd = os.open(os.devnull, os.O_RDONLY)
    try:
        code = _mod.supervise(
            [
                _mod.sys.executable,
                "-c",
                _CHILD,
                str(received),
                str(linger),
                exit_marker,
                str(own_exit),
            ],
            dry_run=dry_run,
            log=_mod.DecisionLog(tmp_path / "decision.log"),
            stdin_fd=stdin_fd,
            poll_seconds=0.05,
            sidecar_dir=tmp_path / "untracked" / "context-sidecar",
            decider=decider,
            restart_coordinator=coordinator,
        )
    finally:
        os.close(stdin_fd)
    return int(code), received


def _noop(**fields: Any) -> Any:
    return _mod.TickOutcome(
        decision_value="noop",
        reason="r",
        payload=fields.pop("payload", None),
        submit=True,
        consume_signal_path=None,
        deferred_log=None,
        **fields,
    )


def _asks_once() -> Any:
    calls = {"n": 0}

    def decider(facts: object) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            return _noop(exit_for_restart=("max-age", "session is 3 days old"))
        return _noop()

    return decider


class TestSuperviseExitForRestart:
    def test_types_exit_then_exits_with_the_dedicated_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        code, received = _run_supervise(tmp_path, monkeypatch, decider=_asks_once())
        assert code == _mod.EXIT_STATUS_RESTART_REQUESTED
        assert b"/exit" in received.read_bytes()
        request = json.loads((tmp_path / "state" / "restart-request.json").read_text())
        assert request["session_id"] == _SESSION
        assert request["plugin"] == "max-age"

    def test_holds_every_other_injection_until_the_child_exits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def decider(facts: object) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                return _noop(exit_for_restart=("max-age", "r"))
            return _noop(payload="HELD-INJECTION")

        # The child ignores /exit for 0.6s, during which ticks keep arriving.
        code, received = _run_supervise(
            tmp_path,
            monkeypatch,
            decider=decider,
            linger=0.6,
            exit_marker="never-matches",
            own_exit=0,
        )
        assert b"HELD-INJECTION" not in received.read_bytes()
        assert code == _mod.EXIT_STATUS_RESTART_REQUESTED

    def test_an_ambiguous_session_keeps_the_session_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        code, received = _run_supervise(
            tmp_path,
            monkeypatch,
            decider=_asks_once(),
            sessions=frozenset({"a", "b"}),
            linger=0.4,
            own_exit=9,
        )
        assert code == 9
        assert not received.exists() or b"/exit" not in received.read_bytes()
        assert not (tmp_path / "state" / "restart-request.json").exists()
        assert "refused" in (tmp_path / "decision.log").read_text()

    def test_a_child_that_ignores_exit_is_abandoned_and_the_session_continues(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def decider(facts: object) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                return _noop(exit_for_restart=("max-age", "r"))
            return _noop(payload="AFTER-ABANDON") if calls["n"] > 12 else _noop()

        code, received = _run_supervise(
            tmp_path,
            monkeypatch,
            decider=decider,
            linger=1.5,
            exit_marker="never-matches",
            own_exit=4,
            wait_seconds=0.3,
        )
        assert code == 4
        assert not (tmp_path / "state" / "restart-request.json").exists()
        assert "abandon" in (tmp_path / "decision.log").read_text()
        # Once abandoned the host injects again.
        assert b"AFTER-ABANDON" in received.read_bytes()

    def test_dry_run_does_not_exit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        code, received = _run_supervise(
            tmp_path, monkeypatch, decider=_asks_once(), linger=0.4, own_exit=6, dry_run=True
        )
        assert code == 6
        assert not received.exists() or b"/exit" not in received.read_bytes()
