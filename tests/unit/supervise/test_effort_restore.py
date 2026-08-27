"""Plan 00278 — supervisor effort restore on model downgrade.

A session downgraded from a higher-ranked model family (fable/mythos) to a
lower one (opus) inherits its previous effort setting — "fable low" must fall
through to "opus xhigh", not "opus low". The supervisor tracks the foreground
sidecar's model family per session and, on a ranked downgrade with the live
effort not already xhigh/max, injects ``/effort xhigh`` once, at the same
injection choke point (idle + empty input box) as the other families.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 20_000.0
_SESSION = "effort-sess-1"


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


def _machine():
    return _mod.CompactStateMachine(_mod.CompactPolicy())


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
    """Tick once on fable, then tick after a switch to opus; return the outcome."""
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine, dry_run=dry_run)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort=effort, ts=_NOW - 0.5)
    return _decide(sidecar_dir, machine, dry_run=dry_run)


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


# ── Downgrade detection → injection ──────────────────────────────────────────


def test_fable_to_opus_downgrade_injects_effort_xhigh(tmp_path: Path) -> None:
    outcome = _downgrade(tmp_path / "cs", _machine())
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort xhigh"
    assert outcome.submit is True


def test_dry_run_injects_visible_marker(tmp_path: Path) -> None:
    outcome = _downgrade(tmp_path / "cs", _machine(), dry_run=True)
    assert outcome.decision_value == "would-effort"
    assert outcome.payload is not None
    assert not outcome.payload.startswith("/effort")
    assert "dry-run" in outcome.payload


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


def test_already_xhigh_does_not_inject(tmp_path: Path) -> None:
    outcome = _downgrade(tmp_path / "cs", _machine(), effort="xhigh")
    assert outcome.payload is None


def test_already_max_does_not_inject(tmp_path: Path) -> None:
    outcome = _downgrade(tmp_path / "cs", _machine(), effort="max")
    assert outcome.payload is None


def test_unknown_effort_still_injects_after_downgrade(tmp_path: Path) -> None:
    outcome = _downgrade(tmp_path / "cs", _machine(), effort=None)
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort xhigh"


# ── Per-model minimum effort (no downgrade needed) ───────────────────────────


def test_opus_below_default_minimum_injects_high(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort high"


def test_fable_low_meets_its_minimum(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_unknown_effort_without_downgrade_does_not_inject(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort=None, ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_downgrade_target_outranks_configured_minimum(tmp_path: Path) -> None:
    # After a fable → opus downgrade the target is xhigh, not opus's plain
    # "high" minimum — even an effort already at "high" gets raised.
    outcome = _downgrade(tmp_path / "cs", _machine(), effort="high")
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort xhigh"


def test_never_lowers_effort_above_floor(tmp_path: Path) -> None:
    # INVARIANT (joseph): this family only ever RAISES effort — a session
    # running above its configured floor is never touched.
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="max", ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_parse_min_effort_levels_overrides_and_ignores_junk() -> None:
    parsed = _mod._parse_min_effort_levels("opus=xhigh, sonnet = medium, bogus=high, opus=nope")
    assert parsed["opus"] == "xhigh"
    assert parsed["sonnet"] == "medium"
    assert parsed["fable"] == _mod._DEFAULT_MIN_EFFORT_LEVELS["fable"]
    assert "bogus" not in parsed


def test_reinject_cooldown_suppresses_stale_reading(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 1.0)
    assert _decide(sidecar_dir, machine).decision_value == "would-effort"
    machine.mark_effort_injection(now_wall=_NOW)
    # The sidecar has not caught up yet — the stale "low" must not re-fire...
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None
    # ...until the cooldown has passed and the effort is STILL below minimum.
    later = _NOW + _mod._EFFORT_REINJECT_COOLDOWN_SECONDS + 1.0
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=later - 1.0)
    retry = _decide(sidecar_dir, machine, facts=_facts(later))
    assert retry.decision_value == "would-effort"


# ── Gates, retry, cap ────────────────────────────────────────────────────────


def test_deferred_while_input_box_not_empty_then_retries(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", ts=_NOW - 0.5)
    busy = _decide(sidecar_dir, machine, facts=_facts(input_line_empty=False))
    assert busy.payload is None
    # Pending survives the deferral; the next unobstructed tick fires.
    retry = _decide(sidecar_dir, machine)
    assert retry.decision_value == "would-effort"


def test_success_mark_clears_pending_and_counts(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    outcome = _downgrade(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    machine.mark_effort_injection(now_wall=_NOW)
    assert machine.effort_injections == 1
    # No re-fire while the family stays downgraded.
    again = _decide(sidecar_dir, machine)
    assert again.payload is None


def test_recovery_clears_pending(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _downgrade(sidecar_dir, machine)
    # Model recovers before the injection ever landed.
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 0.1)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_effort_becoming_xhigh_clears_pending(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _downgrade(sidecar_dir, machine, effort="low")
    # Someone (human or otherwise) already raised the effort.
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=_NOW - 0.1)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_injection_cap(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    for _ in range(_mod._MAX_EFFORT_INJECTIONS):
        machine.mark_effort_injection(now_wall=_NOW - 10_000.0)
    outcome = _downgrade(sidecar_dir, machine)
    assert outcome.payload is None


# ── Model restore (/model flip-back, Task 2b.3) ──────────────────────────────


def _restore_ready_machine(sidecar_dir: Path):
    """Downgrade at _NOW, then return (machine, ts) with the delay elapsed."""
    machine = _machine()
    _downgrade(sidecar_dir, machine)
    machine.mark_effort_injection(now_wall=_NOW)  # effort restore already fired
    later = _NOW + _mod._DEFAULT_MODEL_RESTORE_DELAY_SECONDS + 1.0
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=later - 1.0)
    return machine, later


def test_model_restore_fires_after_delay(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine, later = _restore_ready_machine(sidecar_dir)
    outcome = _decide(sidecar_dir, machine, facts=_facts(later))
    assert outcome.decision_value == "would-model"
    assert outcome.payload == "/model fable"
    assert outcome.submit is True


def test_model_restore_not_before_delay(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _downgrade(sidecar_dir, machine)
    machine.mark_effort_injection(now_wall=_NOW)
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


def test_effort_resets_to_floor_after_successful_flip_back(tmp_path: Path) -> None:
    # The ONE sanctioned effort LOWERING: after our /model restore lands,
    # xhigh drops back to fable's floor. This is now driven by the
    # unconditional coupled-effort mechanism (Plan 00278 continuation) --
    # armed by the HOST the moment the /model injection succeeds, not by a
    # later sidecar reading confirming the switch landed.
    sidecar_dir = tmp_path / "cs"
    machine, later = _restore_ready_machine(sidecar_dir)
    writes: list[bytes] = []
    policy = _mod.CompactPolicy()
    _mod._poll_once(
        machine,
        sidecar_dir=sidecar_dir,
        now_wall=later,
        idle=True,
        dry_run=False,
        master_writer=writes.append,
        log=None,
        freshness_seconds=policy.freshness_seconds,
    )
    after = later + 30.0
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=after - 1.0)
    outcome = _decide(sidecar_dir, machine, facts=_facts(after))
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort low"


def test_no_effort_reset_without_our_restore(tmp_path: Path) -> None:
    # A recovery we did not cause (human flipped back) is left alone.
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _downgrade(sidecar_dir, machine)
    machine.mark_effort_injection(now_wall=_NOW)
    after = _NOW + 60.0
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=after - 1.0)
    outcome = _decide(sidecar_dir, machine, facts=_facts(after))
    assert outcome.payload is None


def test_parse_model_restore_delay() -> None:
    assert _mod._parse_model_restore_delay("300") == 300.0
    assert _mod._parse_model_restore_delay("off") == 0.0
    assert _mod._parse_model_restore_delay("junk") == _mod._DEFAULT_MODEL_RESTORE_DELAY_SECONDS
    assert _mod._parse_model_restore_delay("") == _mod._DEFAULT_MODEL_RESTORE_DELAY_SECONDS


def test_model_restore_disabled_when_delay_off(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _downgrade(sidecar_dir, machine)
    machine.mark_effort_injection(now_wall=_NOW)
    policy = _mod.CompactPolicy(model_restore_delay_seconds=0.0)
    disabled = _mod.CompactStateMachine(policy)
    disabled.import_state(machine.export_state())
    later = _NOW + 1_000_000.0
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=later - 1.0)
    outcome = _decide(sidecar_dir, disabled, facts=_facts(later))
    assert outcome.decision_value != "would-model"


# ── Worker round-trip ────────────────────────────────────────────────────────


def test_effort_state_round_trips_through_export_import(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine, facts=_facts(input_line_empty=False))  # pending, deferred
    clone = _machine()
    clone.import_state(machine.export_state())
    # The clone (a fresh worker) fires from the imported pending state.
    outcome = _decide(sidecar_dir, clone)
    assert outcome.decision_value == "would-effort"
    machine.mark_effort_injection(now_wall=_NOW)
    clone.import_state(machine.export_state())
    assert clone.effort_injections == 1


# ── Coupled effort: "/model switch MUST be followed by /effort" (cont.) ──────
#
# Plan 00278 continuation. The post-flip effort correction must be
# UNCONDITIONAL, never gated on a downgrade episode being open or on a
# later sidecar reading confirming the switch landed -- that gating is
# exactly what let a live defect through: switching opus->fable left effort
# at xhigh (fable's floor is "low"), burning account allowance, because the
# old reset only fired once `note_model_reading` observed the recovery,
# which a manual/no-episode switch never triggers.


def test_model_switch_to_fable_forces_coupled_effort_to_floor_without_downgrade_episode(
    tmp_path: Path,
) -> None:
    """THE SAFETY TEST: switching TO fable always drives effort to its floor.

    No downgrade episode is ever opened here (a fresh machine, exactly the
    manual test-trigger shape) -- the coupled mechanism must still fire.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    # Simulate: the HOST just successfully injected "/model fable" (manual
    # test-trigger path) while the session's live effort is still xhigh.
    machine.arm_coupled_effort(session=_SESSION, family="fable")
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort low"
    assert outcome.submit is True


def test_coupled_target_for_top_family_is_its_configured_floor() -> None:
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="fable")
    assert machine.coupled_effort_pending == f"{_SESSION}:fable:low"


def test_coupled_target_for_non_top_family_is_downgrade_xhigh() -> None:
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="opus")
    assert machine.coupled_effort_pending == f"{_SESSION}:opus:xhigh"


def test_coupled_target_respects_custom_fable_floor_override() -> None:
    policy = _mod.CompactPolicy(
        min_effort_levels={"fable": "medium", "opus": "high", "sonnet": "high", "haiku": "low"}
    )
    machine = _mod.CompactStateMachine(policy)
    machine.arm_coupled_effort(session=_SESSION, family="fable")
    assert machine.coupled_effort_pending == f"{_SESSION}:fable:medium"


def test_coupled_effort_fires_on_the_tick_after_arming(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="opus")
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort xhigh"


def test_coupled_effort_subordinate_to_pending_compaction(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="fable")
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    compacting = sidecar_dir / f"{_SESSION}.compacting"
    compacting.write_text(json.dumps({"ts": _NOW - 1.0, "session_id": _SESSION}), encoding="utf-8")
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-continue"
    # Untouched -- the coupled branch never even ran this tick.
    assert machine.coupled_effort_pending == f"{_SESSION}:fable:low"


def test_coupled_effort_deferred_while_input_box_not_empty_then_retries(
    tmp_path: Path,
) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="fable")
    busy = _decide(sidecar_dir, machine, facts=_facts(input_line_empty=False))
    assert busy.payload is None
    assert machine.coupled_effort_pending == f"{_SESSION}:fable:low"
    retry = _decide(sidecar_dir, machine)
    assert retry.decision_value == "would-effort"
    assert retry.payload == "/effort low"


def test_coupled_effort_pending_round_trips_through_export_import() -> None:
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="fable")
    clone = _machine()
    clone.import_state(machine.export_state())
    assert clone.coupled_effort_pending == f"{_SESSION}:fable:low"


def test_coupled_effort_pending_defaults_to_none_for_legacy_state() -> None:
    machine = _machine()
    legacy_state = machine.export_state()
    legacy_state.pop("coupled_effort_pending", None)
    fresh = _machine()
    fresh.import_state(legacy_state)
    assert fresh.coupled_effort_pending is None


def test_manual_model_switch_arms_coupled_effort_via_poll_once(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _mod.write_model_switch_signal(sidecar_dir, session_id=_SESSION, family="fable", now=_NOW)
    writes: list[bytes] = []
    policy = _mod.CompactPolicy()
    _mod._poll_once(
        machine,
        sidecar_dir=sidecar_dir,
        now_wall=_NOW,
        idle=True,
        dry_run=False,
        master_writer=writes.append,
        log=None,
        freshness_seconds=policy.freshness_seconds,
    )
    assert machine.coupled_effort_pending == f"{_SESSION}:fable:low"
    # A manual test-trigger switch must NOT eat into the auto-restore
    # cap/backoff budget -- that bookkeeping is reserved for the AUTO path.
    assert machine.export_state()["model_restores"] == 0


def test_auto_model_restore_arms_coupled_effort_via_poll_once(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine, later = _restore_ready_machine(sidecar_dir)
    writes: list[bytes] = []
    policy = _mod.CompactPolicy()
    _mod._poll_once(
        machine,
        sidecar_dir=sidecar_dir,
        now_wall=later,
        idle=True,
        dry_run=False,
        master_writer=writes.append,
        log=None,
        freshness_seconds=policy.freshness_seconds,
    )
    assert machine.coupled_effort_pending == f"{_SESSION}:fable:low"
    # The AUTO path DOES count against the restore cap/backoff.
    assert machine.export_state()["model_restores"] == 1


def test_coupled_effort_consumed_once_via_poll_once(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="fable")
    writes: list[bytes] = []
    policy = _mod.CompactPolicy()
    _mod._poll_once(
        machine,
        sidecar_dir=sidecar_dir,
        now_wall=_NOW,
        idle=True,
        dry_run=False,
        master_writer=writes.append,
        log=None,
        freshness_seconds=policy.freshness_seconds,
    )
    assert machine.coupled_effort_pending is None
    assert writes  # the /effort payload was actually written
    # No re-fire on the next tick.
    again = _decide(sidecar_dir, machine)
    assert again.payload is None
