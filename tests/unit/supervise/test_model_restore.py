"""Plan 00278 / Plan 00466 N47 review 3 — live `/model` auto-restore.

`test_effort_restore.py` covered both the (now-deleted) effort floor/coupled
mechanism AND the still-live `/model` auto-restore on a downgrade. Deleting
the whole file with the effort machinery silently dropped mutation coverage
for restore backoff, restore delay, the "off" setting, confirm-Enters,
family ranks and the dry-run marker (Plan 00466 N47 review 3, MAJOR 2).
This file restores exactly the non-effort tests, unchanged in intent, so a
mutation to any of those six behaviours is caught again.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise.conftest import write_attributed_downgrade

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 20_000.0
_SESSION = "restore-sess-1"


def _facts(now: float = _NOW, *, idle: bool = True, input_line_empty: bool = True) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=True,
    )


def _write_sidecar(
    sidecar_dir: Path,
    *,
    session_id: str = _SESSION,
    model_id: str = "claude-fable-5",
    effort: str | None = "low",
    ts: float = _NOW - 1.0,
) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{session_id}.json"
    path.write_text(
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
    return path


def _machine(restore_delay: float | None = None):
    """A machine with the default policy, or an explicit restore delay.

    ``restore_delay=-1.0`` disables auto-restore; a positive value adds an
    extra quiet delay; the default policy restores on the first injectable
    tick after a downgrade (turn-gated).
    """
    if restore_delay is None:
        return _mod.CompactStateMachine(_mod.CompactPolicy())
    return _mod.CompactStateMachine(_mod.CompactPolicy(model_restore_delay_seconds=restore_delay))


def _decide(sidecar_dir: Path, machine, *, dry_run: bool = False, facts: object | None = None):
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=facts or _facts(),
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
    )


def _downgrade(sidecar_dir: Path, machine, *, effort: str | None = "low", dry_run: bool = False):
    """Tick once on fable, then tick after a switch to opus; return the outcome.

    The MACHINE's downgrade, so the platform's own record of it is written too
    (Plan 00328) — an unrecorded drop is a human model change and opens no
    episode.
    """
    write_attributed_downgrade(sidecar_dir, session_id=_SESSION)
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine, dry_run=dry_run)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort=effort, ts=_NOW - 0.5)
    return _decide(sidecar_dir, machine, dry_run=dry_run)


def _restore_ready_machine(sidecar_dir: Path):
    """Downgrade at _NOW, then return (machine, ts) with the delay elapsed."""
    machine = _machine()
    _downgrade(sidecar_dir, machine)
    machine.mark_audit_injection()  # consume the decision-time audit backlog
    later = _NOW + _mod._DEFAULT_MODEL_RESTORE_DELAY_SECONDS + 1.0
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=later - 1.0)
    return machine, later


# ── Family classifier ────────────────────────────────────────────────────────


def test_model_family_recognises_known_families() -> None:
    assert _mod._model_family("claude-fable-5") == "fable"
    assert _mod._model_family("claude-mythos-5") == "fable"
    assert _mod._model_family("claude-opus-4-8") == "opus"
    assert _mod._model_family("claude-sonnet-5") == "sonnet"
    assert _mod._model_family("claude-haiku-4-5-20251001") == "haiku"


def test_model_family_unknown_is_none() -> None:
    assert _mod._model_family("") is None
    assert _mod._model_family("gpt-5") is None


def test_family_ranking_orders_fable_above_opus_above_sonnet_above_haiku() -> None:
    ranks = [_mod._family_rank(f) for f in ("haiku", "sonnet", "opus", "fable")]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == 4


# ── Downgrade detection scope ────────────────────────────────────────────────


def test_upgrade_does_not_inject(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "noop"
    assert outcome.payload is None


def test_stable_model_does_not_inject(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_different_session_switch_is_not_a_downgrade(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, session_id="sess-a", model_id="claude-fable-5", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(
        sidecar_dir,
        session_id="sess-b",
        model_id="claude-opus-5",
        effort="high",
        ts=_NOW + 100.0,
    )
    outcome = _decide(sidecar_dir, machine, facts=_facts(_NOW + 101.0))
    assert outcome.payload is None


# ── Model restore (/model flip-back, Task 2b.3) ──────────────────────────────


def test_model_restore_fires_after_delay(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine, later = _restore_ready_machine(sidecar_dir)
    outcome = _decide(sidecar_dir, machine, facts=_facts(later))
    assert outcome.decision_value == "would-model"
    assert outcome.payload == "/model fable"
    assert outcome.submit is True


def test_model_restore_not_before_delay(tmp_path: Path) -> None:
    # An EXPLICIT extra delay (CCY_MODEL_RESTORE_SECONDS) holds the restore
    # back even after the turn gate would allow it.
    sidecar_dir = tmp_path / "cs"
    machine = _machine(restore_delay=900.0)
    _downgrade(sidecar_dir, machine)
    machine.mark_audit_injection()  # consume the decision-time audit backlog
    soon = _NOW + 5.0
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=soon - 1.0)
    outcome = _decide(sidecar_dir, machine, facts=_facts(soon))
    assert outcome.payload is None


def test_model_restore_sets_confirm_enters(tmp_path: Path) -> None:
    # /model needs the confirming Enter too -- the auto-restore branch sets
    # confirm_enters from the SAME policy value as the manual switch signal.
    sidecar_dir = tmp_path / "cs"
    machine, later = _restore_ready_machine(sidecar_dir)
    outcome = _decide(sidecar_dir, machine, facts=_facts(later))
    assert outcome.confirm_enters == _mod._DEFAULT_MODEL_CONFIRM_ENTERS


def test_model_restore_dry_run_marker(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine, later = _restore_ready_machine(sidecar_dir)
    outcome = _decide(sidecar_dir, machine, dry_run=True, facts=_facts(later))
    assert outcome.decision_value == "would-model"
    assert outcome.payload is not None
    assert not outcome.payload.startswith("/model")
    assert "dry-run" in outcome.payload


def test_model_restore_cap(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine, later = _restore_ready_machine(sidecar_dir)
    for _ in range(_mod._MAX_MODEL_RESTORES):
        machine.mark_model_restore(now_wall=_NOW - 100_000.0)
    outcome = _decide(sidecar_dir, machine, facts=_facts(later))
    assert outcome.payload is None


def test_model_restore_backoff_after_recent_restore(tmp_path: Path) -> None:
    # A re-downgrade soon after a restore must NOT auto-restore again
    # (flip-flop guard): the classifier evidently still fires.
    sidecar_dir = tmp_path / "cs"
    machine, later = _restore_ready_machine(sidecar_dir)
    machine.mark_model_restore(now_wall=later)
    outcome = _decide(sidecar_dir, machine, facts=_facts(later + 5.0))
    assert outcome.decision_value != "would-model"


def test_parse_model_restore_delay() -> None:
    assert _mod._parse_model_restore_delay("300") == 300.0
    assert _mod._parse_model_restore_delay("off") == _mod._MODEL_RESTORE_DISABLED_SENTINEL
    assert _mod._parse_model_restore_delay("junk") == _mod._DEFAULT_MODEL_RESTORE_DELAY_SECONDS
    assert _mod._parse_model_restore_delay("") == _mod._DEFAULT_MODEL_RESTORE_DELAY_SECONDS


def test_model_restore_disabled_when_delay_off(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _downgrade(sidecar_dir, machine)
    machine.mark_audit_injection()  # consume the decision-time audit backlog
    policy = _mod.CompactPolicy(model_restore_delay_seconds=_mod._MODEL_RESTORE_DISABLED_SENTINEL)
    disabled = _mod.CompactStateMachine(policy)
    disabled.import_state(machine.export_state())
    later = _NOW + 1_000_000.0
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=later - 1.0)
    outcome = _decide(sidecar_dir, disabled, facts=_facts(later))
    assert outcome.decision_value != "would-model"
