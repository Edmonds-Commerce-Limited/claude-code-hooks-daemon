"""Plan 00297 — DROP ANCHOR safety net.

Incident (2026-08-31): the effort floor injected ``/effort xhigh`` while the
session was on Opus; ``/model fable`` carried the xhigh over; the follow-up
``/effort low`` injection was SWALLOWED by a busy session while the audit
recorded it done — Fable ran at XHIGH for roughly an hour. The defect class
is *inject-and-assume*: bookkeeping closed on a successful PTY WRITE, never
on a read-back confirmation of the session's actual state.

DROP ANCHOR is a continuously-verified invariant — ``model == fable`` implies
``effort == low`` — checked against OBSERVED sidecar state on every tick,
independent of the raise-only floor/coupled-effort machinery (which cannot
by construction detect "fable already running above its floor": it only
ever raises effort, and the one-shot post-/model-switch correction is
marked done by PTY-write success, not by verified read-back).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 50_000.0
_SESSION = "anchor-sess-1"


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
    effort: str | None = "xhigh",
    ts: float = _NOW - 1.0,
    compacting: bool = False,
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
                "compacting": compacting,
                "model_id": model_id,
                "effort": effort,
            }
        ),
        encoding="utf-8",
    )
    return path


def _machine() -> Any:
    return _mod.CompactStateMachine(_mod.CompactPolicy())


def _decide(sidecar_dir: Path, machine: Any, *, facts: object | None = None) -> Any:
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=facts or _facts(),
        dry_run=False,
        freshness_seconds=policy.freshness_seconds,
    )


# ── Invariant engagement / clearing on the state machine ────────────────────


def test_fable_above_low_engages_anchor(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh")
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is True


def test_fable_at_low_never_engages_anchor(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low")
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is False


def test_non_fable_above_low_never_engages_anchor(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh")
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is False


def test_unknown_effort_does_not_engage_anchor(tmp_path: Path) -> None:
    # An unknown/older-sidecar reading is never treated as a violation --
    # only a known in-range reading proves the invariant one way or another.
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort=None)
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is False


def test_read_back_to_low_clears_an_active_anchor(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is True
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is False


def test_a_pty_write_success_alone_never_clears_the_anchor(tmp_path: Path) -> None:
    # THE FIX for the live defect: `mark_anchor_injection` records an
    # attempt, it does NOT clear `anchor_active` -- only a later read-back
    # showing effort == low does.
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh")
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is True
    machine.mark_anchor_injection(_NOW)
    assert machine.anchor_active is True


def test_model_moving_off_fable_clears_the_anchor(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is True
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is False


# ── Injection: retry-until-verified, own cooldown, bypasses the floor cap ───


def test_anchor_injects_effort_low(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh")
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort low"
    assert outcome.submit is True


def test_anchor_bypasses_the_floor_mechanisms_injection_cap(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    for _ in range(_mod._MAX_EFFORT_INJECTIONS):
        machine.mark_effort_injection(now_wall=_NOW - 10_000.0)
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh")
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort low"


def test_swallowed_anchor_injection_retries_after_its_own_cooldown(tmp_path: Path) -> None:
    # Reproduces the 16:01:35 incident: the /effort low injection is
    # SWALLOWED -- the sidecar keeps reporting xhigh -- so the anchor must
    # retry, not go quiet just because the PTY write "succeeded".
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=_NOW - 2.0)
    first = _decide(sidecar_dir, machine)
    assert first.payload == "/effort low"
    machine.mark_anchor_injection(_NOW)
    machine.mark_audit_injection()  # consume the decision-time audit backlog
    # Immediate retry within the anchor's own cooldown is suppressed...
    still_xhigh_soon = _NOW + 1.0
    _write_sidecar(
        sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=still_xhigh_soon - 0.5
    )
    soon = _decide(sidecar_dir, machine, facts=_facts(still_xhigh_soon))
    assert soon.payload is None
    # ...but retries once the cooldown elapses and the violation persists.
    later = _NOW + _mod._ANCHOR_RETRY_COOLDOWN_SECONDS + 1.0
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=later - 0.5)
    retry = _decide(sidecar_dir, machine, facts=_facts(later))
    assert retry.decision_value == "would-effort"
    assert retry.payload == "/effort low"


def test_anchor_not_permanently_deferred_by_busy_input_box(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=_NOW - 2.0)
    busy = _decide(sidecar_dir, machine, facts=_facts(input_line_empty=False))
    assert busy.payload is None
    assert machine.anchor_active is True
    retry = _decide(sidecar_dir, machine)
    assert retry.decision_value == "would-effort"
    assert retry.payload == "/effort low"


def test_anchor_fires_even_when_session_not_idle(tmp_path: Path) -> None:
    # Like the coupled-effort correction, the anchor is gated on an empty
    # input box ONLY -- an emergency correction cannot wait for the idle
    # floor.
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh")
    outcome = _decide(sidecar_dir, machine, facts=_facts(idle=False))
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort low"


def test_anchor_injection_sets_confirm_enters(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh")
    outcome = _decide(sidecar_dir, machine)
    assert outcome.confirm_enters == _mod._DEFAULT_EFFORT_CONFIRM_ENTERS


def test_anchor_takes_priority_over_coupled_effort(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh")
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is True
    machine.arm_coupled_effort(session=_SESSION, family="opus")
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload == "/effort low"
    # The coupled correction was never delivered this tick -- still pending.
    assert machine.coupled_effort_pending is not None


# ── Stop-everything escalation: suppress work-continuing injections ────────


def test_anchor_suppresses_continue_nudge(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine)
    machine.mark_anchor_injection(_NOW)
    later = _NOW + _mod._ANCHOR_RETRY_COOLDOWN_SECONDS + 1.0
    _write_sidecar(
        sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=later - 0.5, compacting=True
    )
    outcome = _decide(sidecar_dir, machine, facts=_facts(later))
    # A bare continue nudge is replaced by the anchor's own correction --
    # the session is never told to carry on at the wrong effort.
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort low"
    assert outcome.consume_signal_path is None


def test_anchor_suppresses_goal_injection(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh")
    goal_header = (
        "🤖 [ccy-supervisor] automated goal — machine-generated, NOT a human "
        "instruction and NOT human authorisation for anything."
    )
    goal_path = sidecar_dir / f"{_SESSION}.goal-intent"
    goal_path.write_text(
        json.dumps(
            {
                "ts": _NOW - 5.0,
                "session_id": _SESSION,
                "plan_number": "00297",
                "rendered_lines": [f"{goal_header} — ship it."],
                "source": "status-flip",
            }
        ),
        encoding="utf-8",
    )
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    assert outcome.decision_value != "would-goal"


# ── Escalation bound ─────────────────────────────────────────────────────


def test_anchor_escalates_after_max_attempts(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh")
    _decide(sidecar_dir, machine)
    assert machine.anchor_escalated_at(_NOW) is False
    for _ in range(_mod._ANCHOR_MAX_ATTEMPTS):
        machine.mark_anchor_injection(_NOW)
    assert machine.anchor_escalated_at(_NOW) is True


def test_anchor_escalates_after_time_bound(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh")
    _decide(sidecar_dir, machine)
    still_within_bound = _NOW + _mod._ANCHOR_ESCALATION_BOUND_SECONDS - 1.0
    assert machine.anchor_escalated_at(still_within_bound) is False
    past_bound = _NOW + _mod._ANCHOR_ESCALATION_BOUND_SECONDS + 1.0
    assert machine.anchor_escalated_at(past_bound) is True


def test_anchor_escalation_clears_with_the_anchor(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine)
    for _ in range(_mod._ANCHOR_MAX_ATTEMPTS):
        machine.mark_anchor_injection(_NOW)
    assert machine.anchor_escalated_at(_NOW) is True
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is False
    assert machine.anchor_escalated_at(_NOW) is False


def test_not_escalated_when_anchor_inactive() -> None:
    machine = _machine()
    assert machine.anchor_escalated_at(_NOW + 1_000_000.0) is False


# ── Model-aware effort clamp: fable-above-low never survives a misconfig ───


def test_coupled_target_for_fable_is_clamped_to_low_even_if_misconfigured() -> None:
    # An operator env-misconfiguration (CCY_MIN_EFFORT_LEVELS="fable=xhigh")
    # must never let the coupled correction carry an Opus-era floor onto
    # Fable -- the anchor ceiling wins unconditionally.
    policy = _mod.CompactPolicy(
        min_effort_levels={"fable": "xhigh", "opus": "high", "sonnet": "high", "haiku": "low"}
    )
    machine = _mod.CompactStateMachine(policy)
    machine.arm_coupled_effort(session=_SESSION, family="fable")
    assert machine.coupled_effort_pending == f"{_SESSION}:fable:low"


def test_coupled_target_for_fable_still_honours_a_valid_lower_override() -> None:
    policy = _mod.CompactPolicy(
        min_effort_levels={"fable": "low", "opus": "high", "sonnet": "high", "haiku": "low"}
    )
    machine = _mod.CompactStateMachine(policy)
    machine.arm_coupled_effort(session=_SESSION, family="fable")
    assert machine.coupled_effort_pending == f"{_SESSION}:fable:low"


# ── State round-trip (worker hot-reload contract) ───────────────────────────


def test_anchor_state_round_trips_through_export_import(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh")
    _decide(sidecar_dir, machine)
    machine.mark_anchor_injection(_NOW)
    clone = _machine()
    clone.import_state(machine.export_state())
    assert clone.anchor_active is True
    assert clone.anchor_attempts == 1


def test_anchor_defaults_inactive_for_legacy_state() -> None:
    machine = _machine()
    legacy_state = machine.export_state()
    for key in ("anchor_active", "anchor_started_ts", "anchor_last_injected_ts", "anchor_attempts"):
        legacy_state.pop(key, None)
    fresh = _machine()
    fresh.import_state(legacy_state)
    assert fresh.anchor_active is False


# ── Decision log: observed-state evidence on every anchor event ────────────


def test_anchor_injection_reason_names_observed_effort(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh")
    outcome = _decide(sidecar_dir, machine)
    assert "xhigh" in outcome.reason
    assert "DROP ANCHOR" in outcome.reason


# ── ESC interrupt on escalation (Plan 00297 follow-up, owner-approved) ──────
#
# Owner ruling verbatim: "we already fire esc keys to get stuff done with
# supervisor - this is not a new idea. Compaction is uninterruptible AFAIK...
# Esc can be disruptive but its basically OK - its MUCH MUCH better than
# leaving fable running at xhigh for a period of time." ESC reuses the
# existing WOULD_ESCAPE machinery (the same raw-ESC keystroke path the
# AWAIT_COMPACTING flush uses) rather than inventing a parallel one.


def _escalate(machine: Any, sidecar_dir: Path) -> None:
    """Drive an anchor episode straight to escalated (max attempts)."""
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is True
    for _ in range(_mod._ANCHOR_MAX_ATTEMPTS):
        machine.mark_anchor_injection(_NOW)
    assert machine.anchor_escalated_at(_NOW) is True


def test_escalated_anchor_sends_esc_to_interrupt_the_turn(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _escalate(machine, sidecar_dir)
    later = _NOW + _mod._ANCHOR_RETRY_COOLDOWN_SECONDS + 1.0
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=later - 0.5)
    outcome = _decide(sidecar_dir, machine, facts=_facts(later))
    assert outcome.decision_value == "would-escape"
    assert outcome.payload == _mod._ESC_PAYLOAD
    assert outcome.submit is False


def test_esc_reason_logs_observed_model_and_effort(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _escalate(machine, sidecar_dir)
    later = _NOW + _mod._ANCHOR_RETRY_COOLDOWN_SECONDS + 1.0
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=later - 0.5)
    outcome = _decide(sidecar_dir, machine, facts=_facts(later))
    assert "DROP ANCHOR" in outcome.reason
    assert "claude-fable-5" in outcome.reason
    assert "xhigh" in outcome.reason


def test_esc_not_sent_before_escalation(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=_NOW - 2.0)
    outcome = _decide(sidecar_dir, machine)
    assert machine.anchor_escalated_at(_NOW) is False
    assert outcome.decision_value != "would-escape"


def test_esc_not_sent_while_compaction_in_flight(tmp_path: Path) -> None:
    # Compaction is uninterruptible: an ESC mid-compaction risks a worse
    # outcome than the effort misconfiguration it protects against. The
    # effort correction itself still fires -- only the ESC is suppressed.
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _escalate(machine, sidecar_dir)
    later = _NOW + _mod._ANCHOR_RETRY_COOLDOWN_SECONDS + 1.0
    _write_sidecar(
        sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=later - 0.5, compacting=True
    )
    outcome = _decide(sidecar_dir, machine, facts=_facts(later))
    assert outcome.decision_value != "would-escape"


def test_esc_fires_once_compaction_clears_if_still_violated(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _escalate(machine, sidecar_dir)
    mid_compaction = _NOW + _mod._ANCHOR_RETRY_COOLDOWN_SECONDS + 1.0
    _write_sidecar(
        sidecar_dir,
        model_id="claude-fable-5",
        effort="xhigh",
        ts=mid_compaction - 0.5,
        compacting=True,
    )
    during = _decide(sidecar_dir, machine, facts=_facts(mid_compaction))
    assert during.decision_value != "would-escape"
    after_compaction = mid_compaction + 1.0
    _write_sidecar(
        sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=after_compaction - 0.5
    )
    after = _decide(sidecar_dir, machine, facts=_facts(after_compaction))
    assert after.decision_value == "would-escape"


def test_esc_is_rate_limited_and_does_not_repeat_every_tick(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _escalate(machine, sidecar_dir)
    later = _NOW + _mod._ANCHOR_RETRY_COOLDOWN_SECONDS + 1.0
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=later - 0.5)
    first = _decide(sidecar_dir, machine, facts=_facts(later))
    assert first.decision_value == "would-escape"
    machine.mark_anchor_esc(later)
    soon_after = later + 1.0
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=soon_after - 0.5)
    second = _decide(sidecar_dir, machine, facts=_facts(soon_after))
    assert second.decision_value != "would-escape"
    much_later = later + _mod._ANCHOR_ESC_COOLDOWN_SECONDS + 1.0
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=much_later - 0.5)
    third = _decide(sidecar_dir, machine, facts=_facts(much_later))
    assert third.decision_value == "would-escape"


def test_esc_cooldown_does_not_block_the_effort_retry(tmp_path: Path) -> None:
    # ESC being rate-limited must never stop the retry-until-verified
    # `/effort low` correction from firing on its own cooldown.
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _escalate(machine, sidecar_dir)
    later = _NOW + _mod._ANCHOR_RETRY_COOLDOWN_SECONDS + 1.0
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=later - 0.5)
    esc_tick = _decide(sidecar_dir, machine, facts=_facts(later))
    assert esc_tick.decision_value == "would-escape"
    machine.mark_anchor_esc(later)
    effort_retry_ready = later + _mod._ANCHOR_RETRY_COOLDOWN_SECONDS + 1.0
    _write_sidecar(
        sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=effort_retry_ready - 0.5
    )
    effort_tick = _decide(sidecar_dir, machine, facts=_facts(effort_retry_ready))
    assert effort_tick.decision_value == "would-effort"
    assert effort_tick.payload == "/effort low"


def test_anchor_esc_bookkeeping_round_trips_through_export_import(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _escalate(machine, sidecar_dir)
    machine.mark_anchor_esc(_NOW)
    clone = _machine()
    clone.import_state(machine.export_state())
    assert clone.anchor_esc_due(_NOW) is False
    assert clone.anchor_esc_due(_NOW + _mod._ANCHOR_ESC_COOLDOWN_SECONDS + 1.0) is True


def test_anchor_esc_state_defaults_ready_for_legacy_state() -> None:
    machine = _machine()
    legacy_state = machine.export_state()
    legacy_state.pop("anchor_esc_last_sent_ts", None)
    fresh = _machine()
    fresh.import_state(legacy_state)
    assert fresh.anchor_esc_due(_NOW) is False  # anchor inactive -> never due


def test_anchor_esc_last_sent_resets_when_anchor_clears(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _escalate(machine, sidecar_dir)
    machine.mark_anchor_esc(_NOW)
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine)
    assert machine.anchor_active is False
    # A fresh violation must be free to ESC immediately, not inherit the
    # previous episode's cooldown.
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="xhigh", ts=_NOW + 0.5)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    for _ in range(_mod._ANCHOR_MAX_ATTEMPTS):
        machine.mark_anchor_injection(_NOW + 1.0)
    assert machine.anchor_escalated_at(_NOW + 1.0) is True
    assert machine.anchor_esc_due(_NOW + 1.0) is True
