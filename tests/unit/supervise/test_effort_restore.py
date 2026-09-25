"""Plan 00278 — supervisor effort restore on model downgrade.

Redesigned by Plan 00466 N47 (adversarial review 1,
``subagent-reports/260925-n47-review1-opus-5-5.md``): the supervisor holds
almost no opinion of its own about effort. Exactly two sanctioned
interventions exist:

- (a) a ranked DOWNGRADE for the same session raises effort to xhigh
  (RAISE-ONLY) until the family recovers, e.g. "fable low" falls through to
  "opus xhigh" while the session sits on the security fallback;
- (b) the top family (fable) is governed EXCLUSIVELY by the separate,
  continuously-verified DROP ANCHOR invariant (Plan 00297,
  ``test_drop_anchor.py``) -- this file's mechanism holds no opinion of its
  own for it.

Any OTHER family, once no downgrade episode is open, is corrected in EITHER
direction toward whatever Claude Code's own settings.json resolves for the
model on screen; nothing configured means Claude Code's own per-model
default already applies and is never fought.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise.conftest import write_attributed_downgrade, write_settings_json

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


def _machine(restore_delay: float | None = None, *, settings_path: Path | None = None):
    """A machine with the default policy, or an explicit restore delay.

    ``restore_delay=-1.0`` disables auto-restore (isolates the effort
    family); a positive value adds an extra quiet delay; the default policy
    restores on the first injectable tick after a downgrade (turn-gated).
    ``settings_path`` points the USER settings.json cache somewhere real; by
    default (None) it resolves to the isolated empty dir the autouse
    ``_isolate_settings_effort`` fixture points ``CLAUDE_CONFIG_DIR`` at, so
    nothing is configured unless a test says otherwise.
    """
    kwargs: dict[str, object] = {}
    if restore_delay is not None:
        kwargs["model_restore_delay_seconds"] = restore_delay
    if settings_path is not None:
        kwargs["settings_path"] = settings_path
    return _mod.CompactStateMachine(_mod.CompactPolicy(**kwargs))


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


# ── Downgrade detection → xhigh compensation (sanctioned intervention a) ────


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
    outcome = _downgrade(tmp_path / "cs", _machine(restore_delay=-1.0), effort="xhigh")
    assert outcome.payload is None


def test_already_max_does_not_inject(tmp_path: Path) -> None:
    outcome = _downgrade(tmp_path / "cs", _machine(restore_delay=-1.0), effort="max")
    assert outcome.payload is None


def test_unknown_effort_still_injects_after_downgrade(tmp_path: Path) -> None:
    outcome = _downgrade(tmp_path / "cs", _machine(), effort=None)
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort xhigh"


def test_downgrade_target_outranks_configured_minimum(tmp_path: Path) -> None:
    # After a fable → opus downgrade the target is xhigh even when opus is
    # already at "high" — the downgrade compensation always wins.
    outcome = _downgrade(tmp_path / "cs", _machine(), effort="high")
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort xhigh"


# ── No opinion outside a downgrade episode, unless settings.json says so ────


def test_fable_gets_no_opinion_here_regardless_of_live_effort(tmp_path: Path) -> None:
    # Sanctioned intervention (b): DROP ANCHOR (test_drop_anchor.py) is
    # fable's sole authority; this raise/restore mechanism holds none.
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 1.0)
    assert _decide(sidecar_dir, machine).payload is None


def test_nothing_configured_at_all_sends_nothing(tmp_path: Path) -> None:
    # Plan 00466 N47 findings 1 and 5: Claude Code has already applied its
    # own per-model default; a second table must never fight it.
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5-5", effort="medium", ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_unknown_effort_without_downgrade_does_not_inject(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort=None, ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_configured_value_raises_when_live_is_below(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    config_dir = tmp_path / "config"
    write_settings_json(config_dir, effort_level="medium")
    machine = _machine(settings_path=config_dir / "settings.json")
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort medium"


def test_configured_value_lowers_when_live_is_above(tmp_path: Path) -> None:
    # The ONE sanctioned lowering outside the top family: settings.json is
    # the SSoT in both directions, not a raise-only floor.
    sidecar_dir = tmp_path / "cs"
    config_dir = tmp_path / "config"
    write_settings_json(config_dir, effort_level="medium")
    machine = _machine(settings_path=config_dir / "settings.json")
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort medium"


def test_equal_to_configured_sends_nothing(tmp_path: Path) -> None:
    # Owner-shaped settings: top-level medium, per-model medium for both
    # opus-5 and opus-5-5.
    sidecar_dir = tmp_path / "cs"
    config_dir = tmp_path / "config"
    write_settings_json(
        config_dir,
        effort_level="medium",
        model_settings={
            "claude-opus-5": {"effortLevel": "medium"},
            "claude-opus-5-5": {"effortLevel": "medium"},
        },
    )
    machine = _machine(settings_path=config_dir / "settings.json")
    _write_sidecar(sidecar_dir, model_id="claude-opus-5-5", effort="medium", ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_project_settings_overrides_user_settings(monkeypatch, tmp_path: Path) -> None:
    # Plan 00466 N47 finding 2.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "project"))
    write_settings_json(tmp_path / "project" / ".claude", effort_level="low")
    write_settings_json(tmp_path / "user", effort_level="high")
    machine = _machine(settings_path=tmp_path / "user" / "settings.json")
    sidecar_dir = tmp_path / "cs"
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort low"


def test_a_sibling_models_settings_entry_is_never_used(tmp_path: Path) -> None:
    # Plan 00466 N47 finding 3.
    sidecar_dir = tmp_path / "cs"
    config_dir = tmp_path / "config"
    write_settings_json(
        config_dir,
        model_settings={
            "claude-opus-5": {"effortLevel": "xhigh"},
            "claude-opus-5-5": {"effortLevel": "medium"},
        },
    )
    machine = _machine(settings_path=config_dir / "settings.json")
    _write_sidecar(sidecar_dir, model_id="claude-opus-5-5", effort="medium", ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None  # claude-opus-5's xhigh must never apply here


def test_reinject_cooldown_suppresses_stale_reading(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    config_dir = tmp_path / "config"
    write_settings_json(config_dir, effort_level="medium")
    machine = _machine(settings_path=config_dir / "settings.json")
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 1.0)
    assert _decide(sidecar_dir, machine).decision_value == "would-effort"
    machine.mark_effort_injection(now_wall=_NOW)
    machine.mark_audit_injection()  # consume the decision-time audit backlog
    # The sidecar has not caught up yet — the stale "low" must not re-fire...
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None
    # ...until the cooldown has passed and the effort is STILL disagreeing.
    later = _NOW + _mod._EFFORT_REINJECT_COOLDOWN_SECONDS + 1.0
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=later - 1.0)
    # The first `/effort` is the supervisor's own unconfirmed line, so the
    # quiet session gets a follow-up [enter] for it before anything new is
    # typed; the re-inject lands on the tick after.
    follow_up = _decide(sidecar_dir, machine, facts=_facts(later))
    assert follow_up.decision_value == "would-resubmit"
    machine.clear_own_line()
    retry = _decide(sidecar_dir, machine, facts=_facts(later + 1.0))
    assert retry.decision_value == "would-effort"


# ── Gates, retry, cap (downgrade-episode xhigh path) ─────────────────────────


def test_deferred_while_input_box_not_empty_then_retries(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    config_dir = tmp_path / "config"
    write_settings_json(config_dir, effort_level="medium")
    machine = _machine(settings_path=config_dir / "settings.json")
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 2.0)
    busy = _decide(sidecar_dir, machine, facts=_facts(input_line_empty=False))
    assert busy.payload is None
    # Pending survives the deferral; the next unobstructed tick fires.
    retry = _decide(sidecar_dir, machine)
    assert retry.decision_value == "would-effort"


def test_success_mark_clears_pending_and_counts(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine(restore_delay=-1.0)  # isolate the effort family
    outcome = _downgrade(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    machine.mark_effort_injection(now_wall=_NOW)
    machine.mark_audit_injection()  # consume the decision-time audit backlog
    assert machine.effort_injections == 1
    # No re-fire while the family stays downgraded.
    again = _decide(sidecar_dir, machine)
    assert again.payload is None


def test_recovery_clears_pending(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _downgrade(sidecar_dir, machine)
    machine.mark_audit_injection()  # consume the decision-time audit backlog
    # Model recovers before the injection ever landed.
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 0.1)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_effort_becoming_xhigh_clears_pending(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine(restore_delay=-1.0)  # isolate the effort family
    _downgrade(sidecar_dir, machine, effort="low")
    machine.mark_audit_injection()  # consume the decision-time audit backlog
    # Someone (human or otherwise) already raised the effort.
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=_NOW - 0.1)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_injection_cap(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine(restore_delay=-1.0)  # isolate the effort family
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
    machine.mark_audit_injection()  # consume the decision-time audit backlog
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
    # An EXPLICIT extra delay (CCY_MODEL_RESTORE_SECONDS) holds the restore
    # back even after the turn gate would allow it.
    sidecar_dir = tmp_path / "cs"
    machine = _machine(restore_delay=900.0)
    _downgrade(sidecar_dir, machine)
    machine.mark_effort_injection(now_wall=_NOW)
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


def test_floor_effort_injection_sets_confirm_enters(tmp_path: Path) -> None:
    # /effort opens Claude Code's effort selector, which — like /model — needs
    # a SECOND, confirming Enter after the normal submit or the switch never
    # completes (observed live: the coupled /effort fired but sat unconfirmed
    # until a human pressed Enter).
    outcome = _downgrade(tmp_path / "cs", _machine())
    assert outcome.decision_value == "would-effort"
    assert outcome.confirm_enters == _mod._DEFAULT_EFFORT_CONFIRM_ENTERS
    assert outcome.confirm_enters >= 1


def test_effort_confirm_enters_env_parsing() -> None:
    assert _mod._parse_effort_confirm_enters("2") == 2
    assert _mod._parse_effort_confirm_enters("0") == 0
    assert _mod._parse_effort_confirm_enters("junk") == _mod._DEFAULT_EFFORT_CONFIRM_ENTERS
    assert _mod._parse_effort_confirm_enters("-1") == _mod._DEFAULT_EFFORT_CONFIRM_ENTERS


def test_effort_confirm_enters_policy_default() -> None:
    assert _mod.CompactPolicy().effort_confirm_enters == _mod._DEFAULT_EFFORT_CONFIRM_ENTERS


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


def test_drop_anchor_resets_effort_after_successful_flip_back_to_fable(tmp_path: Path) -> None:
    # A restore always lands back on the TOP family (fable is the only
    # family a downgrade episode can start from, Plan 00328's scope rule),
    # so DROP ANCHOR -- not this raise/restore mechanism -- is what brings
    # effort back down once the injected "/model fable" lands and a fresh
    # reading shows it still at xhigh.
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


def test_parse_model_restore_delay() -> None:
    assert _mod._parse_model_restore_delay("300") == 300.0
    assert _mod._parse_model_restore_delay("off") == _mod._MODEL_RESTORE_DISABLED_SENTINEL
    assert _mod._parse_model_restore_delay("junk") == _mod._DEFAULT_MODEL_RESTORE_DELAY_SECONDS
    assert _mod._parse_model_restore_delay("") == _mod._DEFAULT_MODEL_RESTORE_DELAY_SECONDS


def test_model_restore_disabled_when_delay_off(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _downgrade(sidecar_dir, machine)
    machine.mark_effort_injection(now_wall=_NOW)
    machine.mark_audit_injection()  # consume the decision-time audit backlog
    policy = _mod.CompactPolicy(model_restore_delay_seconds=_mod._MODEL_RESTORE_DISABLED_SENTINEL)
    disabled = _mod.CompactStateMachine(policy)
    disabled.import_state(machine.export_state())
    later = _NOW + 1_000_000.0
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=later - 1.0)
    outcome = _decide(sidecar_dir, disabled, facts=_facts(later))
    assert outcome.decision_value != "would-model"


# ── Worker round-trip ────────────────────────────────────────────────────────


def test_effort_state_round_trips_through_export_import(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    config_dir = tmp_path / "config"
    write_settings_json(config_dir, effort_level="medium")
    machine = _machine(settings_path=config_dir / "settings.json")
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 1.0)
    _decide(sidecar_dir, machine, facts=_facts(input_line_empty=False))  # pending, deferred
    clone = _machine(settings_path=config_dir / "settings.json")
    clone.import_state(machine.export_state())
    # The clone (a fresh worker) fires from the imported pending state.
    outcome = _decide(sidecar_dir, clone)
    assert outcome.decision_value == "would-effort"
    machine.mark_effort_injection(now_wall=_NOW)
    clone.import_state(machine.export_state())
    assert clone.effort_injections == 1


# ── Coupled effort: "/model switch is followed by /effort WHEN owed" ────────
#
# Plan 00466 N47 finding 6: the TARGET is resolved at decision time from
# OBSERVED state (an open downgrade episode for the exact destination, or
# settings.json for the model actually on screen), never from which path
# armed the correction. A manual switch to a family with no episode open now
# gets settings-resolved (or nothing), never an automatic xhigh.


def test_arm_coupled_effort_for_fable_resolves_to_nothing_here(tmp_path: Path) -> None:
    # Fable has no opinion in this mechanism at all -- DROP ANCHOR alone.
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="fable")
    assert machine.coupled_effort_pending == f"{_SESSION}:fable"
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None
    assert machine.coupled_effort_pending is None  # cleared: nothing was ever owed here


def test_coupled_target_is_xhigh_while_its_downgrade_episode_is_open(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _downgrade(sidecar_dir, machine, effort="xhigh")  # episode open: session:opus
    machine.arm_coupled_effort(session=_SESSION, family="opus")
    target = machine.resolve_coupled_effort_target(reading=None, now_wall=_NOW)
    assert target == "xhigh"  # resolvable with no reading -- the level never depends on model id


def test_manual_switch_to_opus_with_no_episode_open_gets_no_effort(tmp_path: Path) -> None:
    # THE FIX: this is the shape of the owner's real "restore to Opus"
    # report -- a manual switch, no downgrade episode, nothing configured.
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="opus")
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="medium", ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None
    assert machine.coupled_effort_pending is None  # nothing configured -> satisfied, cleared


def test_manual_switch_to_opus_with_no_episode_open_honours_settings(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    config_dir = tmp_path / "config"
    write_settings_json(config_dir, effort_level="medium")
    machine = _machine(settings_path=config_dir / "settings.json")
    machine.arm_coupled_effort(session=_SESSION, family="opus")
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=_NOW - 1.0)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    assert outcome.payload == "/effort medium"


def test_coupled_effort_waits_for_a_reading_of_the_new_family(tmp_path: Path) -> None:
    # No sidecar reading exists yet showing the destination family -- the
    # correction cannot resolve settings for an unknown model id, so it
    # waits rather than guessing.
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="opus")
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None
    assert machine.coupled_effort_pending == f"{_SESSION}:opus"  # still armed, not cleared


def test_coupled_effort_subordinate_to_pending_compaction(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _downgrade(sidecar_dir, machine, effort="xhigh")
    machine.arm_coupled_effort(session=_SESSION, family="opus")
    compacting = sidecar_dir / f"{_SESSION}.compacting"
    compacting.write_text(json.dumps({"ts": _NOW - 1.0, "session_id": _SESSION}), encoding="utf-8")
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-continue"
    # Untouched -- the coupled branch never even ran this tick.
    assert machine.coupled_effort_pending == f"{_SESSION}:opus"


def test_coupled_effort_deferred_while_input_box_not_empty_then_retries(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _downgrade(sidecar_dir, machine, effort="xhigh")
    machine.arm_coupled_effort(session=_SESSION, family="opus")
    busy = _decide(sidecar_dir, machine, facts=_facts(input_line_empty=False))
    assert busy.payload is None
    assert machine.coupled_effort_pending == f"{_SESSION}:opus"
    retry = _decide(sidecar_dir, machine)
    assert retry.decision_value == "would-effort"
    assert retry.payload == "/effort xhigh"


def test_coupled_effort_pending_round_trips_through_export_import() -> None:
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="opus")
    clone = _machine()
    clone.import_state(machine.export_state())
    assert clone.coupled_effort_pending == f"{_SESSION}:opus"


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
    _mod.write_model_switch_signal(sidecar_dir, session_id=_SESSION, family="opus", now=_NOW)
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
    assert machine.coupled_effort_pending == f"{_SESSION}:opus"
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
    assert machine.coupled_effort_pending == f"{_SESSION}:fable"
    # The AUTO path DOES count against the restore cap/backoff.
    assert machine.export_state()["model_restores"] == 1


def test_coupled_effort_consumed_once_via_poll_once(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine(restore_delay=-1.0)  # isolate from auto-restore
    _downgrade(sidecar_dir, machine, effort="xhigh")
    machine.arm_coupled_effort(session=_SESSION, family="opus")
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
    # The successful silent injection owes ONE visible audit flush...
    audit = _decide(sidecar_dir, machine)
    assert audit.decision_value == "would-audit"
    _mod._apply_post_injection_bookkeeping(machine, audit, injected=True)
    # ...and after it, no coupled-effort re-fire.
    again = _decide(sidecar_dir, machine)
    assert again.payload is None
