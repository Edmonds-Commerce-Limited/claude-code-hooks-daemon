"""Tests for keystroke injection + poll wiring in claude-supervise.py.

Plan 00135 Slice 2. In dry-run the supervisor injects a harmless visible
MARKER; armed it injects the real /compact. These tests exercise the payload
resolver, the injection primitive, the idle gate, the poll tick, and the
select-timeout wiring in `_forward_io` -- all without a real `claude` child.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
Decision = _mod.Decision
CompactPolicy = _mod.CompactPolicy
CompactStateMachine = _mod.CompactStateMachine
InputActivity = _mod.InputActivity
DecisionLog = _mod.DecisionLog

_DRY_COMPACT = "compact suggestion fired from supervisor (dry run mode)"


class TestResolvePayload:
    def test_noop_returns_none(self) -> None:
        assert _mod._resolve_payload(Decision.NOOP, dry_run=True) is None
        assert _mod._resolve_payload(Decision.NOOP, dry_run=False) is None

    def test_dry_run_compact_is_marker(self) -> None:
        assert _mod._resolve_payload(Decision.WOULD_COMPACT, dry_run=True) == _DRY_COMPACT

    def test_dry_run_continue_is_marker(self) -> None:
        payload = _mod._resolve_payload(Decision.WOULD_CONTINUE, dry_run=True)
        assert "continue" in payload and "dry run" in payload

    def test_armed_compact_is_slash_compact(self) -> None:
        assert _mod._resolve_payload(Decision.WOULD_COMPACT, dry_run=False) == "/compact"

    def test_armed_continue_is_continue(self) -> None:
        assert _mod._resolve_payload(Decision.WOULD_CONTINUE, dry_run=False) == "continue"


class TestPerformInjection:
    def test_writes_payload_with_carriage_return(self) -> None:
        written: list[bytes] = []
        _mod._perform_injection(written.append, "hello world")
        assert b"".join(written) == b"hello world\r"


class TestIsIdle:
    def test_no_input_is_idle(self) -> None:
        activity = InputActivity()
        assert _mod._is_idle(activity, now_monotonic=100.0, idle_floor_seconds=2.0) is True

    def test_recent_input_is_not_idle(self) -> None:
        activity = InputActivity()
        activity.last_input_monotonic = 99.5
        assert _mod._is_idle(activity, now_monotonic=100.0, idle_floor_seconds=2.0) is False

    def test_old_input_is_idle(self) -> None:
        activity = InputActivity()
        activity.last_input_monotonic = 90.0
        assert _mod._is_idle(activity, now_monotonic=100.0, idle_floor_seconds=2.0) is True


class TestPollOnce:
    def _sidecar(
        self, directory: Path, *, red: bool, ts: float = 1000.0, compacting: bool | None = None
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {
            "red": red,
            "tier": "red" if red else "green",
            "pct": 85.0,
            "session_id": "s",
            "ts": ts,
            "seq": 1,
            "writer_pid": 1,
        }
        if compacting is not None:
            payload["compacting"] = compacting
        (directory / "s.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_red_idle_injects_marker(self, tmp_path: Path) -> None:
        self._sidecar(tmp_path / "sc", red=True)
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
        )
        assert ev.decision is Decision.WOULD_COMPACT
        assert b"".join(written) == (_DRY_COMPACT + "\r").encode("utf-8")

    def test_not_red_no_injection(self, tmp_path: Path) -> None:
        self._sidecar(tmp_path / "sc", red=False)
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
        )
        assert ev.decision is Decision.NOOP
        assert written == []

    def test_busy_no_injection(self, tmp_path: Path) -> None:
        self._sidecar(tmp_path / "sc", red=True)
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=False,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
        )
        assert ev.decision is Decision.NOOP
        assert written == []

    def test_armed_injects_real_slash_compact(self, tmp_path: Path) -> None:
        self._sidecar(tmp_path / "sc", red=True)
        written: list[bytes] = []
        _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=False,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
        )
        assert b"".join(written) == b"/compact\r"

    def test_injection_is_logged(self, tmp_path: Path) -> None:
        self._sidecar(tmp_path / "sc", red=True)
        log = DecisionLog(tmp_path / "decision.log")
        _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=lambda _b: None,
            log=log,
            freshness_seconds=30.0,
        )
        contents = (tmp_path / "decision.log").read_text(encoding="utf-8")
        assert "would-compact" in contents
        assert "injected" in contents


class TestForwardIoPolling:
    def test_on_poll_runs_on_select_timeout(self) -> None:
        stdin_read_fd, stdin_write_fd = os.pipe()
        master_read_fd, master_write_fd = os.pipe()
        calls = {"count": 0}

        def _on_poll() -> None:
            calls["count"] += 1
            if calls["count"] >= 2:
                # Close the master write end -> EOF makes _forward_io return.
                os.close(master_write_fd)

        try:
            _mod._forward_io(
                stdin_read_fd,
                master_read_fd,
                InputActivity(),
                poll_seconds=0.01,
                on_poll=_on_poll,
            )
        finally:
            os.close(stdin_read_fd)
            os.close(stdin_write_fd)
            os.close(master_read_fd)

        assert calls["count"] >= 2

    def test_stdin_eof_is_dropped_so_polling_still_fires(self) -> None:
        # An EOF stdin is always "readable"; it must be dropped from the watch
        # set so the poll timeout can still fire (else the loop would spin).
        stdin_read_fd, stdin_write_fd = os.pipe()
        os.close(stdin_write_fd)  # immediate EOF on stdin
        master_read_fd, master_write_fd = os.pipe()
        calls = {"count": 0}

        def _on_poll() -> None:
            calls["count"] += 1
            os.close(master_write_fd)  # end the loop after the first poll

        try:
            _mod._forward_io(
                stdin_read_fd,
                master_read_fd,
                InputActivity(),
                poll_seconds=0.01,
                on_poll=_on_poll,
            )
        finally:
            os.close(stdin_read_fd)
            os.close(master_read_fd)

        assert calls["count"] >= 1
