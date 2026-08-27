"""Plan 00281 — flag-cleaning /compact on a repeated downgrade (flip-flop).

Plan 00278 restores the effort floor and flips the model back on a silent
model-family downgrade. But in a session doing security-adjacent work the
main context stays saturated with flag-tripping vocabulary, so the platform
classifier re-downgrades on the next flagged turn — a visible flip-flop. This
plan adds an opt-in, gated ``/compact`` that fires on the SECOND downgrade
(after a prior auto-restore) and instructs the agent to summarise the
sensitive material at a HIGH LEVEL, so the compacted context stops
re-triggering the classifier and the subsequent model-restore sticks.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 30_000.0
_SESSION = "flag-compact-sess-1"


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


def _flag_machine(*, enabled: bool = True):
    """A machine whose policy opts flag-cleaning compaction in (or out)."""
    return _mod.CompactStateMachine(_mod.CompactPolicy(flag_compact_enabled=enabled))


def _decide(sidecar_dir: Path, machine, *, dry_run: bool = False, facts: object | None = None):
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=facts or _facts(),
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
    )


def _downgrade(sidecar_dir: Path, machine, *, effort: str | None = "low") -> None:
    """Tick once on fable, then tick after a switch to opus (opens an episode)."""
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort=effort, ts=_NOW - 0.5)
    _decide(sidecar_dir, machine)


def _flipflop_machine(sidecar_dir: Path, *, enabled: bool = True):
    """A machine in the FLIP-FLOP state: episode open AND one restore already fired.

    Mirrors ``_restore_ready_machine`` in test_effort_restore.py — a downgrade
    opened an episode, the effort restore and its audit backlog have been
    consumed, and one model auto-restore is recorded (so ``_model_restores >=
    1``). The sidecar still reads opus, so the episode stays open.
    """
    machine = _flag_machine(enabled=enabled)
    _downgrade(sidecar_dir, machine)
    machine.mark_effort_injection(now_wall=_NOW)  # effort restore already fired
    machine.mark_model_restore(now_wall=_NOW)  # a model auto-restore already fired
    machine.mark_audit_injection()  # consume the decision-time audit backlog
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=_NOW + 0.5)
    return machine


# ── Config parse + policy default ────────────────────────────────────────────


def test_parse_flag_compact_enabled_true_values() -> None:
    for raw in ("1", "true", "TRUE", "yes", "on", "  On  "):
        assert _mod._parse_flag_compact_enabled(raw) is True


def test_parse_flag_compact_enabled_false_values() -> None:
    for raw in ("0", "false", "no", "off", "", "junk"):
        assert _mod._parse_flag_compact_enabled(raw) is False


def test_flag_compact_enabled_from_env_default_off(monkeypatch) -> None:
    monkeypatch.delenv(_mod._FLAG_COMPACT_ENV_VAR, raising=False)
    assert _mod._flag_compact_enabled_from_env() is _mod._DEFAULT_FLAG_COMPACT_ENABLED
    assert _mod._flag_compact_enabled_from_env() is False


def test_flag_compact_enabled_from_env_reads_toggle(monkeypatch) -> None:
    monkeypatch.setenv(_mod._FLAG_COMPACT_ENV_VAR, "1")
    assert _mod._flag_compact_enabled_from_env() is True
    monkeypatch.setenv(_mod._FLAG_COMPACT_ENV_VAR, "off")
    assert _mod._flag_compact_enabled_from_env() is False


def test_compact_policy_flag_compact_default_off(monkeypatch) -> None:
    monkeypatch.delenv(_mod._FLAG_COMPACT_ENV_VAR, raising=False)
    assert _mod.CompactPolicy().flag_compact_enabled is False


# ── Predicate: flag_compact_due ──────────────────────────────────────────────


def test_flag_compact_due_false_when_disabled(tmp_path: Path) -> None:
    machine = _flipflop_machine(tmp_path / "cs", enabled=False)
    assert machine.flag_compact_due(_NOW + 1.0) is False


def test_flag_compact_due_true_on_flipflop_when_enabled(tmp_path: Path) -> None:
    machine = _flipflop_machine(tmp_path / "cs", enabled=True)
    assert machine.flag_compact_due(_NOW + 1.0) is True


def test_flag_compact_due_false_without_prior_restore(tmp_path: Path) -> None:
    # An open episode but NO model restore yet is a first downgrade, not a
    # flip-flop — the existing model-restore handles it.
    sidecar_dir = tmp_path / "cs"
    machine = _flag_machine(enabled=True)
    _downgrade(sidecar_dir, machine)
    assert machine._model_restores == 0
    assert machine.flag_compact_due(_NOW + 1.0) is False


def test_flag_compact_due_false_without_open_episode() -> None:
    machine = _flag_machine(enabled=True)
    machine.mark_model_restore(now_wall=_NOW)  # restore recorded but no open episode
    assert machine.flag_compact_due(_NOW + 1.0) is False


def test_flag_compact_due_respects_cap(tmp_path: Path) -> None:
    machine = _flipflop_machine(tmp_path / "cs", enabled=True)
    for _ in range(_mod._MAX_FLAG_COMPACTIONS):
        machine.mark_flag_compaction(now_wall=_NOW - 100_000.0)  # long ago (past backoff)
    assert machine.flag_compact_due(_NOW + 1.0) is False


def test_flag_compact_due_respects_backoff(tmp_path: Path) -> None:
    machine = _flipflop_machine(tmp_path / "cs", enabled=True)
    # A fresh compaction that has NOT exhausted the cap still backs off.
    if _mod._MAX_FLAG_COMPACTIONS > 1:
        machine.mark_flag_compaction(now_wall=_NOW)
        assert machine.flag_compact_due(_NOW + 1.0) is False
        assert machine.flag_compact_due(_NOW + _mod._FLAG_COMPACT_BACKOFF_SECONDS + 1.0) is True


# ── State round-trip ─────────────────────────────────────────────────────────


def test_flag_compactions_round_trip(tmp_path: Path) -> None:
    machine = _flipflop_machine(tmp_path / "cs", enabled=True)
    machine.mark_flag_compaction(now_wall=_NOW)
    state = machine.export_state()
    assert state["flag_compactions"] == 1
    fresh = _flag_machine(enabled=True)
    fresh.import_state(state)
    assert fresh.export_state()["flag_compactions"] == 1


# ── decide_once branch ───────────────────────────────────────────────────────


def test_flag_compact_fires_on_flipflop(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _flipflop_machine(sidecar_dir, enabled=True)
    outcome = _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    assert outcome.decision_value == _mod.Decision.WOULD_COMPACT.value
    assert outcome.is_flag_compact is True
    assert outcome.submit is True
    # A REAL /compact with the slash-command first and the flag-cleaning body.
    assert outcome.payload.startswith("/compact ")
    assert "🤖 [ccy-supervisor" in outcome.payload
    assert outcome.payload.endswith(_mod._FLAG_COMPACT_BODY)


def test_flag_compact_arms_audit(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _flipflop_machine(sidecar_dir, enabled=True)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    assert any("flag-cleaning" in item for item in machine.audit_pending)


def test_flag_compact_disabled_by_default(tmp_path: Path) -> None:
    # A machine set up in the flip-flop state but with the feature OFF must not
    # fire a would-compact (default off — auto-compaction is invasive).
    sidecar_dir = tmp_path / "cs"
    machine = _flipflop_machine(sidecar_dir, enabled=False)
    outcome = _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    assert outcome.decision_value != _mod.Decision.WOULD_COMPACT.value


def test_flag_compact_not_on_first_downgrade(tmp_path: Path) -> None:
    # Episode open but zero restores: the model-restore path owns a one-off.
    sidecar_dir = tmp_path / "cs"
    machine = _flag_machine(enabled=True)
    _downgrade(sidecar_dir, machine)
    machine.mark_effort_injection(now_wall=_NOW)
    machine.mark_audit_injection()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=_NOW + 0.5)
    outcome = _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    assert outcome.decision_value != _mod.Decision.WOULD_COMPACT.value


def test_flag_compact_dry_run_marker(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _flipflop_machine(sidecar_dir, enabled=True)
    outcome = _decide(sidecar_dir, machine, dry_run=True, facts=_facts(_NOW + 1.0))
    assert outcome.decision_value == _mod.Decision.WOULD_COMPACT.value
    # A dry-run marker is NOT a real /compact — it must not start the command.
    assert not outcome.payload.startswith("/compact")
    assert _mod._DRY_RUN_FLAG_COMPACT_BODY in outcome.payload


def test_flag_compact_deferred_when_input_box_busy(tmp_path: Path) -> None:
    # can_inject requires an empty input box; a non-empty box defers (idle but
    # box not empty -> the deferred_log sub-branch).
    sidecar_dir = tmp_path / "cs"
    machine = _flipflop_machine(sidecar_dir, enabled=True)
    facts = _facts(_NOW + 1.0, idle=True, input_line_empty=False)
    outcome = _decide(sidecar_dir, machine, facts=facts)
    assert outcome.payload is None
    assert outcome.deferred_log is not None


def test_flag_compact_noop_when_session_not_idle(tmp_path: Path) -> None:
    # not idle at all -> the busy noop_reason_log sub-branch, still no payload.
    sidecar_dir = tmp_path / "cs"
    machine = _flipflop_machine(sidecar_dir, enabled=True)
    facts = _facts(_NOW + 1.0, idle=False, input_line_empty=True)
    outcome = _decide(sidecar_dir, machine, facts=facts)
    assert outcome.payload is None


def test_flag_compact_does_not_shadow_a_pending_compaction_signal(tmp_path: Path) -> None:
    # A live compaction signal drives a resume (would-continue); the flag-compact
    # branch is gated on signal_path is None, so it must yield to the resume.
    sidecar_dir = tmp_path / "cs"
    machine = _flipflop_machine(sidecar_dir, enabled=True)
    (sidecar_dir / f"{_SESSION}.compacting").write_text(
        json.dumps({"ts": _NOW + 1.0, "session_id": _SESSION}), encoding="utf-8"
    )
    outcome = _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    assert outcome.decision_value != _mod.Decision.WOULD_COMPACT.value


# ── Host bookkeeping ─────────────────────────────────────────────────────────


def test_flag_compact_counts_only_on_success(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _flipflop_machine(sidecar_dir, enabled=True)
    outcome = _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    # A failed PTY write keeps the budget so a later tick retries.
    _mod._apply_post_injection_bookkeeping(machine, outcome, injected=False)
    assert machine.export_state()["flag_compactions"] == 0
    # A successful write counts against the cap.
    _mod._apply_post_injection_bookkeeping(machine, outcome, injected=True)
    assert machine.export_state()["flag_compactions"] == 1


def test_flag_compact_does_not_refire_after_success(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _flipflop_machine(sidecar_dir, enabled=True)
    first = _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    _mod._apply_post_injection_bookkeeping(machine, first, injected=True)
    # The cap (default 1) plus backoff prevents an immediate re-fire.
    second = _decide(sidecar_dir, machine, facts=_facts(_NOW + 2.0))
    assert second.decision_value != _mod.Decision.WOULD_COMPACT.value


# ── Worker → host JSON round-trip ────────────────────────────────────────────


def test_is_flag_compact_survives_json_round_trip(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _flipflop_machine(sidecar_dir, enabled=True)
    outcome = _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    restored = _mod._outcome_from_json(_mod._outcome_to_json(outcome))
    assert restored.is_flag_compact is True
    assert restored.decision_value == _mod.Decision.WOULD_COMPACT.value
