"""An effort drop the supervisor did not inject is a human's choice (ledger 00422 N7).

A bare ``/effort`` opens Claude Code's own selector, which types no level the
line recogniser can read, so ``note_manual_effort_command`` never ran and the
per-model floor put the level straight back -- "i just manualy set effort to
medium and supervisor forced it back to high".

The owner's ruling (00422 DECISIONS.md, decision 3): an OBSERVED effort drop
that the supervisor did not itself inject is trusted as manual and latched.
That reads the outcome instead of the keystroke, so the selector, a typed
level and any future route are all covered by the same rule.

It is deliberately the OPPOSITE answer to the model-downgrade question, where
an unattributed model change gets no restore episode. Both answers keep the
supervisor from overriding a human; ``test_attributed_downgrade.py`` pins the
other half.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 70_000.0
_SESSION = "selector-sess-1"
_OTHER_SESSION = "selector-sess-2"


def _facts(now: float) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
    )


def _write_sidecar(
    sidecar_dir: Path,
    *,
    model_id: str,
    effort: str | None,
    ts: float,
    session_id: str = _SESSION,
) -> None:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    for stale in sidecar_dir.glob("*.json"):
        stale.unlink()
    (sidecar_dir / f"{session_id}.json").write_text(
        json.dumps(
            {
                "red": False,
                "critical": False,
                "compact_urgent": False,
                "tier": "ok",
                "pct": 20.0,
                "session_id": session_id,
                "ts": ts,
                "seq": 1,
                "writer_pid": 42,
                "compacting": False,
                "model_id": model_id,
                "effort": effort,
            }
        ),
        encoding="utf-8",
    )


def _machine() -> Any:
    return _mod.CompactStateMachine(_mod.CompactPolicy())


def _tick(
    sidecar_dir: Path,
    machine: Any,
    *,
    step: int,
    model_id: str,
    effort: str | None,
    session_id: str = _SESSION,
    dry_run: bool = False,
) -> Any:
    """Render one reading and run one decision tick ``step`` seconds in."""
    now = _NOW + step
    _write_sidecar(
        sidecar_dir, model_id=model_id, effort=effort, ts=now - 0.5, session_id=session_id
    )
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=_facts(now),
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
    )


# ── The owner's report, reproduced ──────────────────────────────────────────


def test_a_selector_drop_below_the_floor_is_latched_and_not_undone(tmp_path: Path) -> None:
    """opus's floor is ``high``; the human picks ``medium`` from the selector."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _tick(sidecar_dir, machine, step=0, model_id="claude-opus-5", effort="xhigh")

    outcome = _tick(sidecar_dir, machine, step=10, model_id="claude-opus-5", effort="medium")

    assert outcome.payload is None
    assert machine.export_state()["manual_effort_active"] == "medium"


def test_the_latched_drop_stays_honoured_on_later_ticks(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _tick(sidecar_dir, machine, step=0, model_id="claude-opus-5", effort="high")
    _tick(sidecar_dir, machine, step=10, model_id="claude-opus-5", effort="low")

    later = _tick(sidecar_dir, machine, step=400, model_id="claude-opus-5", effort="low")

    assert later.payload is None


def test_the_latch_is_said_out_loud_in_the_decision_log(tmp_path: Path) -> None:
    """A floor that stops acting must say why, or it looks broken."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _tick(sidecar_dir, machine, step=0, model_id="claude-opus-5", effort="xhigh")

    outcome = _tick(sidecar_dir, machine, step=10, model_id="claude-opus-5", effort="medium")

    assert outcome.noop_reason_log is not None
    assert "xhigh -> medium" in outcome.noop_reason_log
    assert "manual" in outcome.noop_reason_log


# ── What is NOT a human drop ────────────────────────────────────────────────


def test_the_supervisors_own_drop_is_not_latched(tmp_path: Path) -> None:
    """DROP ANCHOR types ``/effort low`` on fable; its landing is not a human."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    first = _tick(sidecar_dir, machine, step=0, model_id="claude-fable-5", effort="medium")
    assert first.payload == "/effort low"

    _tick(sidecar_dir, machine, step=10, model_id="claude-fable-5", effort="low")

    assert machine.export_state()["manual_effort_active"] is None


def test_the_own_drop_is_recognised_across_the_sidecar_reporting_lag(tmp_path: Path) -> None:
    """The sidecar refreshes only on a render, so the old level can be reported
    after the injection. The landing arrives later and is still ours."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _tick(sidecar_dir, machine, step=0, model_id="claude-fable-5", effort="medium")
    _tick(sidecar_dir, machine, step=5, model_id="claude-fable-5", effort="medium")
    _tick(sidecar_dir, machine, step=10, model_id="claude-fable-5", effort="medium")

    _tick(sidecar_dir, machine, step=900, model_id="claude-fable-5", effort="low")

    assert machine.export_state()["manual_effort_active"] is None


def test_a_dry_run_decision_injects_nothing_so_attributes_nothing(tmp_path: Path) -> None:
    """In dry-run no ``/effort`` is typed, so a drop that follows is human."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _tick(sidecar_dir, machine, step=0, model_id="claude-fable-5", effort="medium", dry_run=True)

    _tick(sidecar_dir, machine, step=10, model_id="claude-fable-5", effort="low", dry_run=True)

    assert machine.export_state()["manual_effort_active"] == "low"


def test_an_own_injection_is_credited_once_only(tmp_path: Path) -> None:
    """Once the supervisor's level has landed, a later human return to that
    same level is the human's, not a second landing of the old injection."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _tick(sidecar_dir, machine, step=0, model_id="claude-fable-5", effort="medium")
    _tick(sidecar_dir, machine, step=10, model_id="claude-fable-5", effort="low")
    # The anchor is satisfied at low; no fresh injection. Model moves to opus
    # (a new spell) and the human then drops within it.
    _tick(sidecar_dir, machine, step=400, model_id="claude-opus-5", effort="xhigh")

    _tick(sidecar_dir, machine, step=410, model_id="claude-opus-5", effort="low")

    assert machine.export_state()["manual_effort_active"] == "low"


def test_a_rise_is_not_latched(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _tick(sidecar_dir, machine, step=0, model_id="claude-opus-5", effort="high")

    _tick(sidecar_dir, machine, step=10, model_id="claude-opus-5", effort="xhigh")

    assert machine.export_state()["manual_effort_active"] is None


def test_a_drop_across_a_model_change_is_not_latched(tmp_path: Path) -> None:
    """A family change starts a new spell with its own default; the effort it
    arrives at is not a choice made within either spell."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _tick(sidecar_dir, machine, step=0, model_id="claude-opus-5", effort="xhigh")

    _tick(sidecar_dir, machine, step=10, model_id="claude-fable-5", effort="low")

    assert machine.export_state()["manual_effort_active"] is None


def test_a_drop_across_sessions_is_not_latched(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _tick(sidecar_dir, machine, step=0, model_id="claude-opus-5", effort="xhigh")

    _tick(
        sidecar_dir,
        machine,
        step=10,
        model_id="claude-opus-5",
        effort="medium",
        session_id=_OTHER_SESSION,
    )

    assert machine.export_state()["manual_effort_active"] is None


def test_an_unknown_effort_is_no_evidence_either_way(tmp_path: Path) -> None:
    """An older sidecar without the live field says nothing; the comparison
    resumes against the last KNOWN level."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _tick(sidecar_dir, machine, step=0, model_id="claude-opus-5", effort="xhigh")
    _tick(sidecar_dir, machine, step=10, model_id="claude-opus-5", effort=None)
    assert machine.export_state()["manual_effort_active"] is None

    _tick(sidecar_dir, machine, step=20, model_id="claude-opus-5", effort="medium")

    assert machine.export_state()["manual_effort_active"] == "medium"


def test_an_inferred_drop_does_not_cancel_an_armed_coupled_correction() -> None:
    """A typed ``/effort`` cancels the queued post-switch default; an INFERRED
    drop does not. A drop seen between a ``/model`` injection and its coupled
    ``/effort`` is as likely the switch settling as a human, and the coupled
    correction is the invariant that keeps fable off xhigh."""
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="opus")
    reading = _mod.SidecarReading(
        red=False,
        critical=False,
        compact_urgent=False,
        tier="ok",
        pct=20.0,
        session_id=_SESSION,
        ts=_NOW,
        seq=1,
        writer_pid=42,
        compacting=False,
        stale=False,
        model_id="claude-opus-5",
        effort="xhigh",
    )
    machine.note_model_reading(reading, now_wall=_NOW)
    dropped = _mod.replace(reading, ts=_NOW + 1.0, effort="medium")

    machine.note_model_reading(dropped, now_wall=_NOW + 1.0)

    assert machine.export_state()["manual_effort_active"] == "medium"
    assert machine.coupled_effort_pending == f"{_SESSION}:opus"


# ── Hot-reload safety ───────────────────────────────────────────────────────


def test_the_drop_tracking_round_trips_through_export_import(tmp_path: Path) -> None:
    """The worker adopts the host's state every tick, so the last reading and
    the pending own injection must survive the round trip or a reload would
    forget whose drop it is."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _tick(sidecar_dir, machine, step=0, model_id="claude-fable-5", effort="medium")

    clone = _machine()
    clone.import_state(machine.export_state())
    _tick(sidecar_dir, clone, step=10, model_id="claude-fable-5", effort="low")

    assert clone.export_state()["manual_effort_active"] is None
