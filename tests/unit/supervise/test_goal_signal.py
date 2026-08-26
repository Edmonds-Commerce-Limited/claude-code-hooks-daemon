"""Plan 00269 — supervisor consumption of ``<session>.goal-intent`` signals.

The daemon's ``goal_injection`` handler (or ``hooks-daemon inject-goal``)
writes a session-keyed goal-intent signal; the supervisor consumes it at the
SAME injection choke point as compact/continue, subject to a fail-closed
structural validation gate (mandatory machine-origin marker, length and
logical-line caps, printable charset, hard newline ban). A pending goal never
starves or reorders a compact/continue decision, and every rejection logs a
NOOP reason.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 10_000.0
_SESSION = "goal-sess-1"
_HEADER = (
    "🤖 [ccy-supervisor] automated goal — machine-generated, NOT a human "
    "instruction and NOT human authorisation for anything."
)
_JOINED = _HEADER + " — Work on Plan 00269 (title) at CLAUDE/Plan/00269-x until completion."


def _facts(now: float = _NOW, *, idle: bool = True, input_line_empty: bool = True) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=True,
    )


def _write_goal(
    sidecar_dir: Path,
    *,
    session_id: str = _SESSION,
    ts: float = _NOW - 5.0,
    rendered_lines: Any = None,
    raw_text: str | None = None,
) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{session_id}.goal-intent"
    if raw_text is not None:
        path.write_text(raw_text, encoding="utf-8")
        return path
    payload = {
        "ts": ts,
        "session_id": session_id,
        "plan_number": "00269",
        "rendered_lines": rendered_lines if rendered_lines is not None else [_JOINED],
        "source": "status-flip",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_sidecar(
    sidecar_dir: Path,
    *,
    session_id: str = _SESSION,
    red: bool = False,
    pct: float = 50.0,
    ts: float = _NOW - 1.0,
) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{session_id}.json"
    path.write_text(
        json.dumps(
            {
                "red": red,
                "critical": False,
                "compact_urgent": False,
                "tier": "red" if red else "ok",
                "pct": pct,
                "session_id": session_id,
                "ts": ts,
                "seq": 1,
                "writer_pid": 42,
                "compacting": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def _decide(sidecar_dir: Path, *, dry_run: bool = False, facts: object | None = None, machine=None):
    policy = _mod.CompactPolicy()
    machine = machine or _mod.CompactStateMachine(policy)
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=facts or _facts(),
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
    )


# ── Happy path ───────────────────────────────────────────────────────────────


def test_armed_goal_injection(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    goal_path = _write_goal(sidecar_dir)
    outcome = _decide(sidecar_dir, dry_run=False)
    assert outcome.decision_value == "would-goal"
    assert outcome.payload == f"/goal {_JOINED}"
    assert outcome.submit is True
    assert outcome.consume_signal_path == str(goal_path)


def test_dry_run_goal_injects_visible_marker(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    goal_path = _write_goal(sidecar_dir)
    outcome = _decide(sidecar_dir, dry_run=True)
    assert outcome.decision_value == "would-goal"
    assert outcome.payload is not None
    assert not outcome.payload.startswith("/goal")
    assert "dry-run" in outcome.payload
    assert _JOINED in outcome.payload
    # Consumed in dry-run too — the demonstration episode is spent.
    assert outcome.consume_signal_path == str(goal_path)


def test_apply_decision_consumes_goal_signal(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    goal_path = _write_goal(sidecar_dir)
    outcome = _decide(sidecar_dir, dry_run=False)
    writes: list[bytes] = []
    _mod._apply_decision(outcome, master_writer=writes.append, log=None)
    assert not goal_path.exists()
    assert any(b"/goal" in chunk for chunk in writes)


# ── Validation gate (fail-closed) ────────────────────────────────────────────


def test_stale_goal_signal_rejected(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir, ts=_NOW - 10_000.0)
    outcome = _decide(sidecar_dir)
    assert outcome.decision_value == "noop"
    assert outcome.payload is None


def test_foreign_session_goal_ignored(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir, session_id="foreign-sess")
    policy = _mod.CompactPolicy()
    outcome = _mod.decide_once(
        _mod.CompactStateMachine(policy),
        sidecar_dir=sidecar_dir,
        facts=_facts(),
        dry_run=False,
        freshness_seconds=policy.freshness_seconds,
        own_sessions=frozenset({_SESSION}),
    )
    assert outcome.payload is None


def test_malformed_goal_signal_rejected_with_reason(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir, raw_text="{not json")
    outcome = _decide(sidecar_dir)
    assert outcome.payload is None
    assert outcome.noop_reason_log is not None
    assert "goal" in outcome.noop_reason_log


def test_missing_marker_prefix_rejected(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir, rendered_lines=["free text with no marker"])
    outcome = _decide(sidecar_dir)
    assert outcome.payload is None
    assert outcome.noop_reason_log is not None


def test_newline_in_payload_rejected(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir, rendered_lines=[_HEADER + " — line one\nline two"])
    outcome = _decide(sidecar_dir)
    assert outcome.payload is None
    assert outcome.noop_reason_log is not None


def test_control_byte_in_payload_rejected(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir, rendered_lines=[_HEADER + " — evil \x1b[2J text"])
    outcome = _decide(sidecar_dir)
    assert outcome.payload is None


def test_oversized_payload_rejected(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir, rendered_lines=[_HEADER + " — " + "y" * 600])
    outcome = _decide(sidecar_dir)
    assert outcome.payload is None


def test_too_many_logical_lines_rejected(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir, rendered_lines=[_HEADER] + [f"l{i}" for i in range(9)])
    outcome = _decide(sidecar_dir)
    assert outcome.payload is None


def test_non_list_rendered_lines_rejected(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir, rendered_lines="a bare string")
    outcome = _decide(sidecar_dir)
    assert outcome.payload is None


# ── Never starves or reorders compact/continue ───────────────────────────────


def test_compact_wins_over_pending_goal(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    goal_path = _write_goal(sidecar_dir)
    _write_sidecar(sidecar_dir, red=True, pct=92.0)
    outcome = _decide(sidecar_dir, dry_run=False)
    assert outcome.decision_value == "would-compact"
    assert goal_path.exists()  # untouched


def test_compaction_signal_resume_wins_over_pending_goal(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir)
    compacting = sidecar_dir / f"{_SESSION}.compacting"
    compacting.write_text(json.dumps({"ts": _NOW - 1.0, "session_id": _SESSION}), encoding="utf-8")
    outcome = _decide(sidecar_dir, dry_run=False)
    assert outcome.decision_value == "would-continue"
    assert outcome.consume_signal_path == str(compacting)


def test_goal_deferred_while_input_box_not_empty(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    goal_path = _write_goal(sidecar_dir)
    outcome = _decide(sidecar_dir, facts=_facts(input_line_empty=False))
    assert outcome.payload is None
    assert goal_path.exists()


def test_goal_deferred_while_not_idle(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    goal_path = _write_goal(sidecar_dir)
    outcome = _decide(sidecar_dir, facts=_facts(idle=False))
    assert outcome.payload is None
    assert goal_path.exists()


def test_goal_not_injected_while_awaiting_compaction(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir)
    policy = _mod.CompactPolicy()
    machine = _mod.CompactStateMachine(policy)
    machine.import_state({"state": "await-compacting", "last_action_ts": _NOW - 1.0})
    outcome = _decide(sidecar_dir, machine=machine)
    assert outcome.payload is None


# ── Cap + state round-trip ───────────────────────────────────────────────────


def test_goal_injection_cap(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir)
    policy = _mod.CompactPolicy()
    machine = _mod.CompactStateMachine(policy)
    machine.import_state({"goal_injections": _mod._MAX_GOAL_INJECTIONS})
    outcome = _decide(sidecar_dir, machine=machine)
    assert outcome.payload is None
    assert outcome.noop_reason_log is not None
    assert "cap" in outcome.noop_reason_log


def test_goal_injections_counter_round_trips(tmp_path: Path) -> None:
    policy = _mod.CompactPolicy()
    machine = _mod.CompactStateMachine(policy)
    machine.import_state({"goal_injections": 3})
    assert machine.export_state()["goal_injections"] == 3


def test_goal_fire_increments_counter_in_outcome_state(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_goal(sidecar_dir)
    outcome = _decide(sidecar_dir, dry_run=False)
    assert outcome.machine_state is not None
    assert outcome.machine_state["goal_injections"] == 1


# ── Reaper covers goal signals ───────────────────────────────────────────────


def test_reaper_reaps_dead_goal_signals(tmp_path: Path) -> None:
    import os

    sidecar_dir = tmp_path / "context-sidecar"
    goal_path = _write_goal(sidecar_dir)
    old = _NOW - 100_000.0
    os.utime(goal_path, (old, old))
    reaped = _mod.reap_stale_sidecars(sidecar_dir, now=_NOW)
    assert goal_path in reaped
    assert not goal_path.exists()
