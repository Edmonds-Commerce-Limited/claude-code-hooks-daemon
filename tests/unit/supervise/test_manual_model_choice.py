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

import pytest

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
    human_model_selector: bool = False,
) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=True,
        human_model_command=human_model_command,
        human_effort_command=human_effort_command,
        human_model_selector=human_model_selector,
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


def test_human_input_line_reports_a_bare_model_as_a_selector_submission() -> None:
    """A bare `/model` names no family, but it IS a deliberate switch starting.

    Field defect: `/model` + Enter opens Claude Code's own picker, and the
    family is then chosen with arrow keys that carry no text. Recognising only
    `/model <arg>` therefore missed the most common way a human switches
    model, and the auto-restore flipped the session straight back.
    """
    line = _mod.HumanInputLine()
    line.feed(b"/model\r")
    assert line.take_model_selector_submitted() is True
    # Consume-once, like every other typed-command edge.
    assert line.take_model_selector_submitted() is False


def test_human_input_line_selector_edge_not_raised_by_a_targeted_model_command() -> None:
    """`/model opus` latches the FAMILY; it must not also arm the wildcard."""
    line = _mod.HumanInputLine()
    line.feed(b"/model opus\r")
    assert line.take_model_submitted() == "opus"
    assert line.take_model_selector_submitted() is False


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
    """A typed command outside the backstop window no longer counts as manual."""
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


def test_manual_command_survives_long_busy_spell(tmp_path: Path) -> None:
    """Field defect (2026-09-02 live test): the session stayed BUSY after the
    human typed /model opus, so the first opus sidecar reading arrived minutes
    later -- past the old 120s window -- and the supervisor fought the human's
    own choice with an auto-restore. The manual note is a latch consumed by the
    first matching reading, however late it arrives (backstop expiry only)."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(human_model_command="opus"))
    late = _NOW + 600.0  # ten busy minutes later
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=late - 0.5)
    outcome = _decide(sidecar_dir, machine, facts=_facts(late))
    assert outcome.payload is None
    even_later = _decide(sidecar_dir, machine, facts=_facts(late + 10_000.0))
    assert even_later.decision_value != "would-model"


def test_manual_match_is_consumed_by_first_matching_reading(tmp_path: Path) -> None:
    """Once the typed choice is observed landing, the latch is spent: a LATER
    silent drop to the same family is a substitution again and must restore."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(human_model_command="opus"))
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    assert _decide(sidecar_dir, machine).payload is None  # manual match consumed here
    # The human goes back up to fable...
    t1 = _NOW + 10.0
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=t1 - 0.5)
    _decide(sidecar_dir, machine, facts=_facts(t1))
    # ...then a SILENT drop to opus (nothing typed) must be classified silent.
    t2 = _NOW + 20.0
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=t2 - 0.5)
    outcome = _decide(sidecar_dir, machine, facts=_facts(t2))
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


@pytest.mark.parametrize(
    "typed_argument",
    [
        "opus",  # the plain canonical form
        "Opus",  # capitalised, as a human naturally types it
        "OPUS",
        "opusplan",  # a real Claude Code model alias
        "claude-opus-4-8",  # a full model id pasted verbatim
        "claude-opus-5",
    ],
)
def test_raw_typed_model_argument_forms_all_latch(tmp_path: Path, typed_argument: str) -> None:
    """The RAW argument the human typed must latch, in every form they may type.

    This feeds the argument exactly as `HumanInputLine` hands it over. The
    previous version of this test canonicalised with `_model_family()` in the
    TEST before passing it in, so it only ever exercised the already-canonical
    string and hid a real defect: the raw argument was stored verbatim and
    compared with `==` against the canonical family, so `/model Opus` (or any
    alias or full id) failed to latch and the auto-restore overrode the
    human's own choice.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(human_model_command=typed_argument))
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None
    later = _decide(sidecar_dir, machine, facts=_facts(_NOW + 10_000.0))
    assert later.decision_value != "would-model"


def test_manual_marker_records_the_canonical_family(tmp_path: Path) -> None:
    """The daemon compares the marker against a CANONICAL family, so a raw
    typed form must be canonicalised before it is written or the status-line
    indicator never recognises the manual change."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(human_model_command="Opus"))
    marker_path = tmp_path / _mod._MANUAL_MODEL_MARKER_SUBDIR / f"{_SESSION}.json"
    assert json.loads(marker_path.read_text(encoding="utf-8"))["family"] == "opus"


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


def test_decide_once_never_writes_to_the_global_worker_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """decide_once must log only through its INJECTED DecisionLog.

    ``append_worker_error`` resolves a GLOBAL path, so a call from decide_once
    lands in the LIVE session's worker log even from a unit-test tick.
    """
    calls: list[str] = []
    monkeypatch.setattr(_mod, "append_worker_error", calls.append)
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine, facts=_facts(human_model_command="opus"))
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW + 0.5)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    assert calls == []


def test_marker_write_deferred_until_session_known(tmp_path: Path) -> None:
    """A typed /model on a tick with no reading and no tracked session must not
    lose the marker: it stays pending and is written on the first tick that can
    name the session (field defect: no marker file ever appeared live)."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    # No sidecar on disk yet: the typed command cannot name a session.
    _decide(sidecar_dir, machine, facts=_facts(human_model_command="opus"))
    marker_path = tmp_path / _mod._MANUAL_MODEL_MARKER_SUBDIR / f"{_SESSION}.json"
    assert not marker_path.exists()
    # The session's sidecar appears -> the pending marker is written now.
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW + 4.5)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 5.0))
    assert marker_path.exists()
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    assert payload["family"] == "opus"


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
    assert clone._typed_model_matches("opus", _NOW + 1.0) is True


def test_legacy_state_without_manual_fields_defaults_safely() -> None:
    machine = _machine()
    legacy_state = machine.export_state()
    legacy_state.pop("manual_model_family", None)
    legacy_state.pop("manual_model_ts", None)
    legacy_state.pop("manual_effort_active", None)
    fresh = _machine()
    fresh.import_state(legacy_state)
    assert fresh._typed_model_matches("opus", _NOW) is False
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


# ── Scope: ONLY the automated fable security downgrade ──────────────────────


def test_opus_to_sonnet_drop_is_not_the_supervisors_business(tmp_path: Path) -> None:
    """Owner ruling (2026-09-04, from a live dogfood): this family exists ONLY
    to counteract the automated fable security downgrade, NOTHING more.

    Field evidence -- the human picked Sonnet and the supervisor typed
    `/model opus` at them 4s later, then forced `/effort xhigh`:

        07:14:55 would-model: downgrade quiet delay elapsed -> injected '/model opus'
        07:14:58 would-effort: model switch requires coupled effort -> '/effort xhigh'

    A drop that did not START at fable is not the security fallback, so no
    episode opens: no restore, and no forced xhigh either.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-sonnet-5", effort="high", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "noop"
    later = _decide(sidecar_dir, machine, facts=_facts(_NOW + 10_000.0))
    assert later.decision_value == "noop"
    assert machine.export_state()["downgrade_episode"] is None


def test_opus_to_haiku_drop_is_also_ignored(tmp_path: Path) -> None:
    """The rule is 'started at fable', not 'dropped by only one rank'."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-haiku-4-5", effort="low", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine)
    assert machine.export_state()["downgrade_episode"] is None


def test_the_fable_security_downgrade_is_still_restored(tmp_path: Path) -> None:
    """The one case the family exists for must keep working exactly as before."""
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


def test_a_fable_drop_all_the_way_to_sonnet_still_counts(tmp_path: Path) -> None:
    """The fallback target is opus today, but the rule keys on where the drop
    STARTED -- so a fallback to anything below fable is still covered."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-sonnet-5", effort="high", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine)
    assert machine.export_state()["downgrade_episode"] is not None


# ── The `/model` PICKER: a manual choice with no family in the typed text ────


def test_model_selector_choice_suppresses_the_auto_restore(tmp_path: Path) -> None:
    """Field defect: a human out of fable allowance switches to opus through
    the picker, and the supervisor flips the session straight back."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    # The human submits a bare `/model` and picks Opus from the picker; the
    # arrow keys that choose it carry no text, so this edge is all we get.
    _decide(sidecar_dir, machine, facts=_facts(human_model_selector=True))
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "noop"
    later = _decide(sidecar_dir, machine, facts=_facts(_NOW + 10_000.0))
    assert later.decision_value != "would-model"


def test_model_selector_choice_writes_the_shared_manual_marker(tmp_path: Path) -> None:
    """The status-line downgrade badge must not contradict the picker either.

    The family is unknown when the picker opens, so the marker can only be
    written once a reading names what actually landed.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(human_model_selector=True))
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    marker_path = tmp_path / _mod._MANUAL_MODEL_MARKER_SUBDIR / f"{_SESSION}.json"
    assert marker_path.exists()
    assert json.loads(marker_path.read_text(encoding="utf-8"))["family"] == "opus"


def test_model_selector_latch_expires(tmp_path: Path) -> None:
    """The picker latch is a WILDCARD -- any family landing counts as chosen --
    so it expires far sooner than the typed-command backstop. Past it, a rank
    drop is a silent substitution again."""
    assert _mod._MANUAL_MODEL_SELECTOR_WINDOW_SECONDS < _mod._MANUAL_MODEL_WINDOW_SECONDS
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(human_model_selector=True))
    stale = _NOW + _mod._MANUAL_MODEL_SELECTOR_WINDOW_SECONDS + 30.0
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=stale - 0.5)
    outcome = _decide(sidecar_dir, machine, facts=_facts(stale))
    assert outcome.decision_value == "would-effort"


def test_model_selector_latch_is_consumed_by_the_family_that_lands(tmp_path: Path) -> None:
    """One picker interaction sanctions ONE change. A later fable drop with
    nothing newly typed is a silent substitution the classifier must catch."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(human_model_selector=True))
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    assert machine.export_state()["manual_selector_ts"] is None
    # Back on fable, then a further unrequested drop: the spent latch must not
    # vouch for it, so a real episode opens.
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW + 1.5)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 2.0))
    _write_sidecar(sidecar_dir, model_id="claude-sonnet-5", effort="high", ts=_NOW + 2.5)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 3.0))
    assert machine.export_state()["downgrade_episode"] is not None


def test_supervisor_auto_restore_does_not_spend_the_picker_latch(tmp_path: Path) -> None:
    """The exact field sequence, and the reason the wildcard needs a guard.

    The human opens the picker BECAUSE they saw the bounce, so a pending
    auto-restore landing mid-interaction is the likely ordering, not the rare
    one. The restore is a family change and an UPGRADE, so it slips past the
    downgrade branch -- and if it consumed the latch, the human's actual pick
    would arrive unlatched and get bounced all over again.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    # A genuine silent substitution opens an episode.
    _write_sidecar(sidecar_dir, model_id="claude-sonnet-5", effort="high", ts=_NOW - 4.0)
    _decide(sidecar_dir, machine, facts=_facts(_NOW - 3.5))
    # The human opens the picker...
    _decide(sidecar_dir, machine, facts=_facts(_NOW - 3.0, human_model_selector=True))
    # ...and the supervisor's own restore lands first, back to where we fell from.
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 2.0)
    _decide(sidecar_dir, machine, facts=_facts(_NOW - 1.5))
    # Now the human's actual choice lands. It must still count as manual.
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.decision_value == "noop"
    later = _decide(sidecar_dir, machine, facts=_facts(_NOW + 10_000.0))
    assert later.decision_value != "would-model"


def test_picker_latch_does_not_cross_into_another_session(tmp_path: Path) -> None:
    """The wildcard is scoped to the session that was foreground when the picker
    opened. Unscoped, it disarmed the auto-restore for a session the human never
    touched -- `_downgrade_episode` is session-keyed for the same reason."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(human_model_selector=True))
    # Foreground moves to a different session, which then suffers a REAL silent
    # drop. The other session's picker must not vouch for it.
    (sidecar_dir / f"{_SESSION}.json").unlink()
    _write_sidecar(sidecar_dir, session_id="other-sess", model_id="claude-fable-5", ts=_NOW)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    _write_sidecar(
        sidecar_dir,
        session_id="other-sess",
        model_id="claude-sonnet-5",
        effort="high",
        ts=_NOW + 1.5,
    )
    outcome = _decide(sidecar_dir, machine, facts=_facts(_NOW + 2.0))
    assert outcome.decision_value == "would-effort"


def test_picker_switch_clears_a_manual_effort_from_the_previous_spell(tmp_path: Path) -> None:
    """Both routes to a manual model change must start a fresh model spell.

    A typed `/model` clears the manual `/effort` latch at note time; the picker
    can only do it where the switch is OBSERVED. Without this the two paths
    diverge permanently and a picker switch silently inherits the old model's
    effort.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _decide(sidecar_dir, machine, facts=_facts(human_effort_command="low"))
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _decide(sidecar_dir, machine, facts=_facts(human_model_selector=True))
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    assert machine.export_state()["manual_effort_active"] is None


def test_typed_model_command_also_retires_a_pending_picker_latch() -> None:
    """Picker opened, escaped, then a family typed instead: one interaction, one
    latch. Leaving the wildcard live is one more way it outlives its moment."""
    machine = _machine()
    machine.note_manual_model_selector(now_wall=_NOW)
    machine.note_manual_model_command("opus", now_wall=_NOW + 1.0)
    assert machine.export_state()["manual_selector_ts"] is None


def test_human_input_line_selector_edge_ignores_a_longer_command() -> None:
    line = _mod.HumanInputLine()
    line.feed(b"/modelfoo\r")
    assert line.take_model_selector_submitted() is False


@pytest.mark.parametrize("typed", [b"/modl\r", b"/mdel\r", b"/model\r"])
def test_autocompleted_model_command_still_arms_the_picker_latch(typed: bytes) -> None:
    """Field evidence (2026-09-04 dogfood): the worker observed `'/modl'`, not
    `/model`.

    Claude Code's slash autocomplete completes the word in its OWN UI, so the
    completed text never crosses the PTY -- only the prefix the human actually
    typed, plus the menu keystrokes. Exact matching therefore misses the real
    submission, which is how a deliberate model change went unrecognised and
    got overridden.

    Erring towards "assume human" is the correct direction here: the owner
    ruling is that a human-driven selection must NEVER be overridden, so a
    false positive costs only a restore we were told not to make anyway.
    """
    line = _mod.HumanInputLine()
    line.feed(typed)
    assert line.take_model_selector_submitted() is True


@pytest.mark.parametrize("typed", [b"/m\r", b"/mo\r", b"/compact\r", b"/goal\r", b"hello\r"])
def test_short_or_unrelated_stems_do_not_arm_the_picker_latch(typed: bytes) -> None:
    """The guess has to stop somewhere, and a two-character stem is where."""
    line = _mod.HumanInputLine()
    line.feed(typed)
    assert line.take_model_selector_submitted() is False


@pytest.mark.parametrize("typed", [b"/mod\r", b"/mode\r"])
def test_a_partial_prefix_of_model_does_not_arm_the_picker_latch(typed: bytes) -> None:
    """A PREFIX is ambiguous -- it may be heading for another command entirely.

    Verified against this environment rather than assumed: `/mode` is a real
    skill in THIS repo and is a prefix of `/model`, so accepting prefixes
    would arm the wildcard on a command that has nothing to do with models,
    silently disabling the fable restore for the latch window. A non-prefix
    subsequence like `/modl` carries no such ambiguity.
    """
    line = _mod.HumanInputLine()
    line.feed(typed)
    assert line.take_model_selector_submitted() is False


def test_autocompleted_model_command_is_still_observed_as_a_slash_line() -> None:
    """The diagnostic that CAUGHT this must keep recording the raw bytes."""
    line = _mod.HumanInputLine()
    line.feed(b"/modl\r")
    assert line.take_slash_submitted() == ["/modl"]


def test_model_selector_state_round_trips_through_export_import() -> None:
    machine = _machine()
    machine.note_manual_model_selector(now_wall=_NOW)
    restored = _machine()
    restored.import_state(machine.export_state())
    assert restored.export_state()["manual_selector_ts"] == _NOW
    assert restored.export_state()["manual_selector_session"] == (
        machine.export_state()["manual_selector_session"]
    )


def test_tick_facts_model_selector_round_trips_through_json() -> None:
    facts = _facts(human_model_selector=True)
    assert _mod._facts_from_json(_mod._facts_to_json(facts)).human_model_selector is True


def test_tick_facts_model_selector_defaults_to_false() -> None:
    facts = _mod.TickFacts(
        now_wall=_NOW,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
    )
    assert facts.human_model_selector is False
