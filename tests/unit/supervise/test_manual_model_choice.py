"""Plan 00316 — manual model choice must win.

A human TYPING `/model <family>` through the PTY input path is a deliberate
choice, not a silent downgrade: the auto-restore must never fight it, and the
coupled per-model default effort must never override a manual `/effort`. A
silent substitution (no typed command in the validity window) keeps working
exactly as before -- it is the classifier's only remaining job.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 30_000.0
_SESSION = "manual-sess-1"


def _facts(
    now: float = _NOW,
    *,
    idle: bool = True,
    input_line_empty: bool = True,
    human_model_command: str | None = None,
    human_effort_command: str | None = None,
) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=True,
        human_model_command=human_model_command,
        human_effort_command=human_effort_command,
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


def _machine() -> object:
    return _mod.CompactStateMachine(_mod.CompactPolicy())


def _decide(sidecar_dir: Path, machine: object, *, facts: object | None = None) -> object:
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=facts or _facts(),
        dry_run=False,
        freshness_seconds=policy.freshness_seconds,
    )


# ── HumanInputLine: recognising a typed /model or /effort line ──────────────


def test_human_input_line_captures_submitted_model_command() -> None:
    line = _mod.HumanInputLine()
    line.feed(b"/model opus\r")
    assert line.take_model_submitted() == "opus"
    # Consume-once: a second read returns None.
    assert line.take_model_submitted() is None


def test_human_input_line_captures_submitted_effort_command() -> None:
    line = _mod.HumanInputLine()
    line.feed(b"/effort low\r")
    assert line.take_effort_submitted() == "low"
    assert line.take_effort_submitted() is None


def test_human_input_line_ignores_bare_model_with_no_argument() -> None:
    line = _mod.HumanInputLine()
    line.feed(b"/model\r")
    assert line.take_model_submitted() is None


def test_human_input_line_ignores_unrelated_text() -> None:
    line = _mod.HumanInputLine()
    line.feed(b"hello world\r")
    assert line.take_model_submitted() is None
    assert line.take_effort_submitted() is None


def test_human_input_line_handles_backspace_before_submit() -> None:
    line = _mod.HumanInputLine()
    line.feed(b"/model opu\x7f\x7fpus\r")  # typo-correct to "opus"
    assert line.take_model_submitted() == "opus"


# ── Manual /model command suppresses the downgrade episode ──────────────────


def test_manual_model_command_suppresses_downgrade_no_restore(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    # The human types /model opus...
    _decide(sidecar_dir, machine, facts=_facts(human_model_command="opus"))
    # ...and the next reading shows the switch landed.
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "noop"
    assert outcome.payload is None
    # No downgrade episode ever opened, so an elapsed quiet delay never fires
    # an auto-restore either.
    later = _decide(sidecar_dir, machine, facts=_facts(_NOW + 10_000.0))
    assert later.decision_value != "would-model"


def test_manual_model_command_logs_no_restore_reason(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(human_model_command="opus"))
    outcome = _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine, facts=_facts(_NOW + 2.0))
    assert outcome.noop_reason_log is not None
    assert "manual" in outcome.noop_reason_log
    assert "no restore" in outcome.noop_reason_log


def test_silent_substitution_without_typed_command_still_restores(tmp_path: Path) -> None:
    """Nothing typed in the window -> the classifier keeps working unchanged."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "would-effort"
    later = _NOW + _mod._DEFAULT_MODEL_RESTORE_DELAY_SECONDS + 1.0
    machine.mark_effort_injection(now_wall=_NOW)
    machine.mark_audit_injection()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=later - 1.0)
    restore = _decide(sidecar_dir, machine, facts=_facts(later))
    assert restore.decision_value == "would-model"
    assert restore.payload == "/model fable"


def test_manual_model_window_expires(tmp_path: Path) -> None:
    """A typed command outside the validity window no longer counts as manual."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(human_model_command="opus"))
    stale = _NOW + _mod._MANUAL_MODEL_WINDOW_SECONDS + 30.0
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=stale - 0.5)
    outcome = _decide(sidecar_dir, machine, facts=_facts(stale))
    # Outside the window this is once again a silent downgrade -> effort floor fires.
    assert outcome.decision_value == "would-effort"


def test_rapid_successive_manual_model_changes_each_count(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0, human_model_command="opus"))
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW + 1.5)
    first = _decide(sidecar_dir, machine, facts=_facts(_NOW + 2.0))
    assert first.payload is None
    # Immediately typed again, dropping further to haiku.
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 3.0, human_model_command="haiku"))
    _write_sidecar(sidecar_dir, model_id="claude-haiku-4-5", effort="high", ts=_NOW + 3.5)
    second = _decide(sidecar_dir, machine, facts=_facts(_NOW + 4.0))
    assert second.payload is None


def test_case_and_alias_forms_of_model_names_match(tmp_path: Path) -> None:
    """The typed command may be an alias (`mythos`) or a full model id."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    # Typed as the raw sidecar-style id; _model_family() canonicalises both.
    typed_family = _mod._model_family("claude-opus-4-8")
    _decide(sidecar_dir, machine, facts=_facts(human_model_command=typed_family))
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_manual_match_clears_a_stale_open_downgrade_episode(tmp_path: Path) -> None:
    """A manual choice wins outright, even over an already-open silent episode."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    # A silent drop opens an episode...
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 2.0)
    opened = _decide(sidecar_dir, machine)
    assert opened.decision_value == "would-effort"
    machine.mark_effort_injection(now_wall=_NOW - 2.0)
    machine.mark_audit_injection()
    # ...then the human deliberately types a further drop to sonnet.
    _decide(sidecar_dir, machine, facts=_facts(_NOW - 1.0, human_model_command="sonnet"))
    _write_sidecar(sidecar_dir, model_id="claude-sonnet-5", effort="high", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None
    later = _decide(sidecar_dir, machine, facts=_facts(_NOW + 10_000.0))
    assert later.decision_value != "would-model"


# ── Task 1.3: shared marker for the daemon's downgrade indicator ────────────


def test_manual_model_command_writes_a_shared_marker(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(_NOW, human_model_command="opus"))
    marker_path = tmp_path / _mod._MANUAL_MODEL_MARKER_SUBDIR / f"{_SESSION}.json"
    assert marker_path.exists()
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    assert payload["family"] == "opus"
    assert payload["session_id"] == _SESSION


def test_write_manual_model_marker_is_atomic_and_readable(tmp_path: Path) -> None:
    path = _mod.write_manual_model_marker(tmp_path, session_id=_SESSION, family="opus", now=_NOW)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"session_id": _SESSION, "family": "opus", "ts": _NOW}


# ── Task 2.1: manual /effort wins over the coupled default ──────────────────


def test_manual_effort_wins_over_per_model_floor(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    # The human explicitly sets effort low on opus (below its "high" default).
    _decide(sidecar_dir, machine, facts=_facts(human_effort_command="low"))
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_manual_effort_wins_within_the_same_model_spell(tmp_path: Path) -> None:
    """A manual /effort beats the FLOOR default for as long as the model
    does not change again -- no /model injection means arm_coupled_effort
    is never called, so nothing re-applies the family's default."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    machine.note_manual_effort_command("low", now_wall=_NOW)
    # opus's per-model default is "high" -- without the manual latch this
    # would fire "/effort high".
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None


def test_model_change_re_applies_its_own_default_over_a_prior_manual_effort() -> None:
    """Owner clarification: precedence is TIME-ORDERED, not absolute. EVERY
    model change (manual switch or auto-restore) starts a fresh spell and
    re-applies ITS default -- even over a manual /effort set under the
    PREVIOUS model. `arm_coupled_effort` only ever runs right after a real
    /model switch, so it must win regardless of an earlier manual latch."""
    machine = _machine()
    # The human set effort low while on fable...
    machine.note_manual_effort_command("low", now_wall=_NOW)
    # ...then manually switches to sonnet: the switch is armed with sonnet's
    # OWN default (xhigh, the non-top-family target), not fable's low.
    machine.arm_coupled_effort(session=_SESSION, family="sonnet")
    assert machine.coupled_effort_pending == f"{_SESSION}:sonnet:xhigh"
    assert machine.export_state()["manual_effort_active"] is None


def test_manual_effort_after_the_reset_still_wins_for_its_own_spell(
    tmp_path: Path,
) -> None:
    """A manual /effort typed AFTER a model-change's auto-applied default
    still wins for the remainder of THAT spell."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    machine.arm_coupled_effort(session=_SESSION, family="sonnet")  # spell starts
    machine.note_manual_effort_command("low", now_wall=_NOW)  # human overrides it
    _write_sidecar(sidecar_dir, model_id="claude-sonnet-5", effort="low", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    # The per-model floor (sonnet's default "high") must not re-fire over it.
    assert outcome.payload is None


def test_manual_effort_cleared_by_next_manual_model_change() -> None:
    machine = _machine()
    machine.note_manual_effort_command("low", now_wall=_NOW)
    machine.note_manual_model_command("opus", now_wall=_NOW + 1.0)
    assert machine.export_state()["manual_effort_active"] is None
    # The coupled default can fire again after the manual model change.
    machine.arm_coupled_effort(session=_SESSION, family="opus")
    assert machine.coupled_effort_pending == f"{_SESSION}:opus:xhigh"


def test_manual_effort_cleared_by_a_further_manual_effort_change() -> None:
    machine = _machine()
    machine.note_manual_effort_command("low", now_wall=_NOW)
    machine.note_manual_effort_command("high", now_wall=_NOW + 1.0)
    assert machine.export_state()["manual_effort_active"] == "high"


def test_manual_effort_state_round_trips_through_export_import() -> None:
    machine = _machine()
    machine.note_manual_effort_command("medium", now_wall=_NOW)
    clone = _machine()
    clone.import_state(machine.export_state())
    assert clone.export_state()["manual_effort_active"] == "medium"


def test_manual_model_state_round_trips_through_export_import() -> None:
    machine = _machine()
    machine.note_manual_model_command("opus", now_wall=_NOW)
    clone = _machine()
    clone.import_state(machine.export_state())
    assert clone._manual_model_matches("opus", _NOW + 1.0) is True


def test_legacy_state_without_manual_fields_defaults_safely() -> None:
    machine = _machine()
    legacy_state = machine.export_state()
    legacy_state.pop("manual_model_family", None)
    legacy_state.pop("manual_model_ts", None)
    legacy_state.pop("manual_effort_active", None)
    fresh = _machine()
    fresh.import_state(legacy_state)
    assert fresh._manual_model_matches("opus", _NOW) is False
    fresh.arm_coupled_effort(session=_SESSION, family="fable")
    assert fresh.coupled_effort_pending == f"{_SESSION}:fable:low"


# ── TickFacts / worker JSON round-trip ───────────────────────────────────────


def test_tick_facts_model_and_effort_commands_round_trip_through_json() -> None:
    facts = _mod.TickFacts(
        now_wall=_NOW,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
        human_model_command="opus",
        human_effort_command="low",
    )
    line = _mod._facts_to_json(facts)
    restored = _mod._facts_from_json(line)
    assert restored.human_model_command == "opus"
    assert restored.human_effort_command == "low"


def test_tick_facts_commands_default_to_none() -> None:
    facts = _mod.TickFacts(
        now_wall=_NOW,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
    )
    assert facts.human_model_command is None
    assert facts.human_effort_command is None


def test_submitted_slash_lines_are_observable() -> None:
    """Any submitted line starting with '/' is recorded verbatim (bounded),
    whether or not a command recogniser matched it — the worker logs these
    so a recognition MISS (e.g. autocomplete swallowing the argument) is
    diagnosable from the field instead of invisible."""
    line = _mod.HumanInputLine()
    line.feed(b"/model opus\r")
    line.feed(b"hello there\r")
    line.feed(b"/mod\t\r")
    assert line.take_slash_submitted() == ["/model opus", "/mod\t"]
    assert line.take_slash_submitted() == []
