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
from typing import TYPE_CHECKING

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


def _decide(sidecar_dir: Path, *, dry_run: bool = False) -> object:
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


# ── Reaping ──────────────────────────────────────────────────────────────────


def test_reaper_reaps_dead_records(tmp_path: Path) -> None:
    trigger = _write_trigger(tmp_path)
    written = _mod.write_goal_clear_record(tmp_path, trigger_path=trigger, now=_NOW)
    old = _NOW - 100_000.0
    os.utime(written, (old, old))
    reaped = _mod.reap_stale_sidecars(tmp_path, now=_NOW)
    assert written in reaped
    assert not written.exists()
