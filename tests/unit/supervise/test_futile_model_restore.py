"""Plan 00328 Phase 1 — a restore that cannot land must stop at one attempt.

Reproduced live on an allowance-exhausted account
(`CLAUDE/Plan/00328-.../REPRODUCTION.md`): the supervisor injected
`/model fable`, the API answered 429, and because nothing checked whether the
switch had LANDED it went on to inject a coupled `/effort low` for a model
that was never on screen, then an unrequested `/compact` after reading its own
failure as a downgrade flip-flop.

None of this needs to know WHY the restore failed. The next reading either
shows the family or it does not.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 40_000.0
_SESSION = "futile-sess-1"


def _facts(now: float = _NOW) -> object:
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


def _machine(*, flag_compact: bool = False) -> object:
    return _mod.CompactStateMachine(_mod.CompactPolicy(flag_compact_enabled=flag_compact))


def _decide(sidecar_dir: Path, machine: object, *, now: float = _NOW) -> object:
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=_facts(now),
        dry_run=False,
        freshness_seconds=policy.freshness_seconds,
    )


def _open_episode_and_fire_restore(
    sidecar_dir: Path, machine: object, *, now: float = _NOW
) -> object:
    """Drive fable -> opus, then take the auto-restore decision the way the host does."""
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=now - 10.0)
    _decide(sidecar_dir, machine, now=now - 9.0)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=now - 8.0)
    _decide(sidecar_dir, machine, now=now - 7.0)
    machine.mark_effort_injection(now_wall=now - 7.0)
    machine.mark_audit_injection()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=now - 6.0)
    restore = _decide(sidecar_dir, machine, now=now - 5.0)
    assert restore.decision_value == "would-model"
    assert restore.payload == "/model fable"
    # What `_apply_post_injection_bookkeeping` does on a successful PTY WRITE.
    machine.mark_model_restore(
        now_wall=now - 5.0,
        family=restore.model_switch_family,
        session=restore.model_switch_session,
    )
    machine.arm_coupled_effort(
        session=restore.model_switch_session or "",
        family=restore.model_switch_family or "",
    )
    return restore


def test_a_restore_that_never_lands_is_not_attempted_again(tmp_path: Path) -> None:
    """The 429 case. The PTY write succeeded; the model change did not."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _open_episode_and_fire_restore(sidecar_dir, machine)
    # The next reading still shows opus -- the switch did not take.
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=_NOW - 1.0)
    _decide(sidecar_dir, machine)
    later = _decide(sidecar_dir, machine, now=_NOW + 10_000.0)
    assert later.decision_value != "would-model"


def test_a_restore_that_lands_leaves_the_family_usable(tmp_path: Path) -> None:
    """No regression for the case the machinery exists for: the security
    downgrade, where the flip-back genuinely works."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _open_episode_and_fire_restore(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=_NOW - 1.0)
    _decide(sidecar_dir, machine)
    assert machine.export_state()["unavailable_families"] == []
    assert machine.export_state()["downgrade_episode"] is None


def test_a_failed_restore_does_not_fire_the_flag_compact(tmp_path: Path) -> None:
    """The worst of the cascade. `flag_compact_due` read 'a restore fired and
    the episode is still open' as a classifier flip-flop, when in fact the
    restore had simply failed. A rate limit must not cost a context wipe."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine(flag_compact=True)
    _open_episode_and_fire_restore(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=_NOW - 1.0)
    _decide(sidecar_dir, machine)
    for tick in range(4):
        outcome = _decide(sidecar_dir, machine, now=_NOW + 10.0 * (tick + 1))
        assert outcome.decision_value != "would-compact"


def test_a_failed_restore_cancels_its_coupled_effort(tmp_path: Path) -> None:
    """The coupled correction targets the floor of the family we switched TO.
    When that switch never happened it is simply wrong -- in the reproduction
    it drove effort to fable's `low` while the session sat on opus."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _open_episode_and_fire_restore(sidecar_dir, machine)
    assert machine.coupled_effort_pending is not None
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert machine.coupled_effort_pending is None
    assert outcome.payload != "/effort low"


def test_unavailable_families_round_trip_through_export_import(tmp_path: Path) -> None:
    """The worker restarts; the knowledge that fable cannot be served must not."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _open_episode_and_fire_restore(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=_NOW - 1.0)
    _decide(sidecar_dir, machine)
    restored = _machine()
    restored.import_state(machine.export_state())
    assert restored.export_state()["unavailable_families"] == ["fable"]
