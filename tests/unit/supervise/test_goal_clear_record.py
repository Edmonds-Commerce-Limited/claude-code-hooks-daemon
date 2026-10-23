"""Plan 00501 Task 8.2 — the supervisor records every clearing ``/goal`` it types.

Claude Code's transcript records a ``/goal clear`` identically whoever typed it,
so the daemon can only tell the supervisor's clear from a human's by a record
the supervisor writes BEFORE typing. These tests pin the writer, its place in
``decide_once``, the fail-closed path (no record, no clear), and that the
daemon's reader accepts what the supervisor writes.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import TYPE_CHECKING, Any

import pytest

from claude_code_hooks_daemon.core.goal_clear_attribution import (
    GOAL_CLEAR_RECORD_SUFFIX,
    read_clear_record,
    record_path,
)
from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 10_000.0
_SESSION = "clear-sess-1"


def _facts(now: float = _NOW) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
    )


def _write_trigger(sidecar_dir: Path, *, session_id: str = _SESSION) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{session_id}.goal-clear"
    path.write_text(json.dumps({"session_id": session_id, "ts": _NOW - 5.0}), encoding="utf-8")
    return path


def _decide(sidecar_dir: Path, *, dry_run: bool = False) -> Any:
    # Any: the supervisor is loaded from a script path, so its DecisionOutcome type is not importable.
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        _mod.CompactStateMachine(policy),
        sidecar_dir=sidecar_dir,
        facts=_facts(),
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
    )


# ── The writer ────────────────────────────────────────────────────────────────


def test_suffix_matches_the_daemon_reader() -> None:
    assert _mod._GOAL_CLEAR_RECORD_SUFFIX == GOAL_CLEAR_RECORD_SUFFIX


def test_record_is_not_picked_up_as_a_clear_trigger(tmp_path: Path) -> None:
    trigger = _write_trigger(tmp_path)
    written = _mod.write_goal_clear_record(tmp_path, trigger_path=trigger, now=_NOW)
    assert written not in set(tmp_path.glob(_mod._GOAL_CLEAR_GLOB))


def test_writer_produces_a_record_the_daemon_attributes(tmp_path: Path) -> None:
    trigger = _write_trigger(tmp_path)
    written = _mod.write_goal_clear_record(tmp_path, trigger_path=trigger, now=_NOW)
    assert written == record_path(tmp_path, _SESSION)
    record = read_clear_record(written)
    assert record is not None
    assert record.session == _SESSION
    assert record.ts == _NOW
    assert record.command == _mod._GOAL_CLEAR_COMMAND


def test_writer_leaves_no_temp_file(tmp_path: Path) -> None:
    trigger = _write_trigger(tmp_path)
    _mod.write_goal_clear_record(tmp_path, trigger_path=trigger, now=_NOW)
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


# ── Its place in decide_once ─────────────────────────────────────────────────


def test_armed_clear_writes_the_record_before_typing(tmp_path: Path) -> None:
    _write_trigger(tmp_path)
    outcome = _decide(tmp_path)
    assert outcome.payload == _mod._GOAL_CLEAR_COMMAND
    record = read_clear_record(record_path(tmp_path, _SESSION))
    assert record is not None
    assert record.ts == _NOW


def test_dry_run_writes_no_record(tmp_path: Path) -> None:
    _write_trigger(tmp_path)
    outcome = _decide(tmp_path, dry_run=True)
    assert outcome.decision_value == "would-goal-clear"
    assert not record_path(tmp_path, _SESSION).exists()


def test_unwritable_record_means_no_clear_is_typed(tmp_path: Path) -> None:
    """An unrecorded clear would be attributed to the human, so it is not typed."""
    trigger = _write_trigger(tmp_path)
    record_path(tmp_path, _SESSION).mkdir()
    outcome = _decide(tmp_path)
    assert outcome.payload is None
    assert outcome.decision_value != "would-goal-clear"
    assert outcome.consume_signal_path is None
    assert outcome.noop_reason_log is not None
    assert "attribution record" in outcome.noop_reason_log
    assert trigger.exists()


# ── A failed write leaves no temp file (review D5) ──────────────────────────


def test_failed_temp_write_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trigger = _write_trigger(tmp_path)

    def _partial_write(self: Path, data: str, encoding: str | None = None) -> int:
        self.write_bytes(data[:3].encode("utf-8"))
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pathlib.Path, "write_text", _partial_write)
    with pytest.raises(OSError, match="No space left"):
        _mod.write_goal_clear_record(tmp_path, trigger_path=trigger, now=_NOW)
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert not record_path(tmp_path, _SESSION).exists()


def test_temp_file_that_cannot_be_removed_is_named_in_the_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trigger = _write_trigger(tmp_path)

    def _partial_write(self: Path, data: str, encoding: str | None = None) -> int:
        self.write_bytes(b"{")
        raise OSError(28, "No space left on device")

    def _refuse_unlink(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(pathlib.Path, "write_text", _partial_write)
    monkeypatch.setattr(pathlib.Path, "unlink", _refuse_unlink)
    with pytest.raises(OSError) as raised:
        _mod.write_goal_clear_record(tmp_path, trigger_path=trigger, now=_NOW)
    message = str(raised.value)
    assert "No space left" in message
    assert ".tmp" in message
    assert "Permission denied" in message


# ── A clear that is not typed leaves no record (review D4) ──────────────────


class _Writer:
    def __init__(self, *, fail: bool = False, fail_after: int | None = None) -> None:
        self.fail = fail
        self.fail_after = fail_after
        self.chunks: list[bytes] = []

    def __call__(self, data: bytes) -> None:
        if self.fail or (self.fail_after is not None and len(self.chunks) >= self.fail_after):
            raise OSError(5, "Input/output error")
        self.chunks.append(data)


def _apply(outcome: Any, writer: _Writer, *, confirmed: bool = True) -> bool:
    return bool(
        _mod._apply_decision(
            outcome, master_writer=writer, log=None, main_focus_confirmed=confirmed
        )
    )


@pytest.fixture
def _no_submit_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_mod.time, "sleep", lambda _seconds: None)


@pytest.mark.usefixtures("_no_submit_delay")
def test_typed_clear_keeps_its_record(tmp_path: Path) -> None:
    trigger = _write_trigger(tmp_path)
    outcome = _decide(tmp_path)
    writer = _Writer()
    assert _apply(outcome, writer) is True
    assert writer.chunks
    assert record_path(tmp_path, _SESSION).exists()
    assert not trigger.exists()


def test_clear_held_at_apply_removes_its_record(tmp_path: Path) -> None:
    """A human `/goal clear` after a held one must not be credited to the supervisor."""
    trigger = _write_trigger(tmp_path)
    outcome = _decide(tmp_path)
    assert record_path(tmp_path, _SESSION).exists()
    writer = _Writer()
    assert _apply(outcome, writer, confirmed=False) is False
    assert writer.chunks == []
    assert not record_path(tmp_path, _SESSION).exists()
    assert trigger.exists()


def test_clear_held_in_the_worker_outcome_path_removes_its_record(tmp_path: Path) -> None:
    _write_trigger(tmp_path)
    outcome = _decide(tmp_path)
    machine = _mod.CompactStateMachine(_mod.CompactPolicy())
    injected = _mod._apply_worker_outcome(
        outcome,
        machine=machine,
        line=_mod.HumanInputLine(),
        master_writer=_Writer(),
        log=None,
        main_focus_confirmed=False,
        now_wall=_NOW,
    )
    assert injected is False
    assert not record_path(tmp_path, _SESSION).exists()


@pytest.mark.usefixtures("_no_submit_delay")
def test_failed_pty_write_removes_its_record(tmp_path: Path) -> None:
    trigger = _write_trigger(tmp_path)
    outcome = _decide(tmp_path)
    with pytest.raises(OSError, match="Input/output error"):
        _apply(outcome, _Writer(fail=True))
    assert not record_path(tmp_path, _SESSION).exists()
    assert trigger.exists()


@pytest.mark.usefixtures("_no_submit_delay")
def test_partial_pty_write_keeps_its_record(tmp_path: Path) -> None:
    """The text reached the box and may still be submitted: it is the supervisor's."""
    _write_trigger(tmp_path)
    outcome = _decide(tmp_path)
    writer = _Writer(fail_after=1)
    with pytest.raises(OSError, match="Input/output error"):
        _apply(outcome, writer)
    assert writer.chunks
    assert record_path(tmp_path, _SESSION).exists()


def test_held_clear_whose_record_cannot_be_removed_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_trigger(tmp_path)
    outcome = _decide(tmp_path)
    lines: list[str] = []

    class _Log:
        def write(self, line: str) -> None:
            lines.append(line)

        def write_noop(self, line: str) -> None:
            lines.append(line)

    def _refuse_unlink(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(pathlib.Path, "unlink", _refuse_unlink)
    injected = _mod._apply_decision(
        outcome, master_writer=_Writer(), log=_Log(), main_focus_confirmed=False
    )
    assert injected is False
    assert any("record" in line and "Permission denied" in line for line in lines)


def test_held_dry_run_clear_touches_no_record(tmp_path: Path) -> None:
    _write_trigger(tmp_path)
    outcome = _decide(tmp_path, dry_run=True)
    assert _apply(outcome, _Writer(), confirmed=False) is False
    assert not record_path(tmp_path, _SESSION).exists()


# ── Reaping ──────────────────────────────────────────────────────────────────


def test_reaper_reaps_dead_records(tmp_path: Path) -> None:
    trigger = _write_trigger(tmp_path)
    written = _mod.write_goal_clear_record(tmp_path, trigger_path=trigger, now=_NOW)
    old = _NOW - 100_000.0
    os.utime(written, (old, old))
    reaped = _mod.reap_stale_sidecars(tmp_path, now=_NOW)
    assert written in reaped
    assert not written.exists()
