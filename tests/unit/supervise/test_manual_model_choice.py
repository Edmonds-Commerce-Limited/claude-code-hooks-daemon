"""A model change the HUMAN makes must win (Plan 00316, rebuilt by Plan 00328).

The invariant is unchanged: the auto-restore must never fight a model the human
chose, and the coupled per-model default effort must never override a manual
`/effort`. What changed is where the answer comes from.

Plan 00316 inferred it NEGATIVELY, from typed keystrokes -- a `/model <family>`
latch, a bare-`/model` picker wildcard, a fuzzy stem for what autocomplete had
swallowed. None of it could work: the picker is navigated with arrow keys that
carry no text, so "nothing was typed" is exactly what a human model change
looks like.

Plan 00328 inverts it. The episode opens only on a downgrade CLAUDE CODE
RECORDED as its own (`write_attributed_downgrade` here, the daemon's
`model_downgrade_recorder` in the field). A model the human picks emits no such
record, so it is respected without being recognised -- and these tests assert
the recognition is GONE, not merely unused.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise.conftest import write_attributed_downgrade

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
    human_effort_command: str | None = None,
) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=True,
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


# ── HumanInputLine: /effort is recognised, /model deliberately is not ────────


def test_human_input_line_captures_submitted_effort_command() -> None:
    line = _mod.HumanInputLine()
    line.feed(b"/effort low\r")
    assert line.take_effort_submitted() == "low"
    # Consume-once: a second read returns None.
    assert line.take_effort_submitted() is None


def test_human_input_line_ignores_unrelated_text() -> None:
    line = _mod.HumanInputLine()
    line.feed(b"hello world\r")
    assert line.take_effort_submitted() is None


def test_human_input_line_handles_backspace_before_submit() -> None:
    line = _mod.HumanInputLine()
    line.feed(b"/effort lo\x7f\x7fhigh\r")  # typo-correct to "high"
    assert line.take_effort_submitted() == "high"


@pytest.mark.parametrize(
    "attribute",
    ["take_model_submitted", "take_model_selector_submitted"],
)
def test_the_line_parser_no_longer_recognises_a_model_command(attribute: str) -> None:
    """The keystroke path is deleted, not disabled.

    A dormant recogniser is an invitation to re-wire it to the restore the next
    time a downgrade is missed, which is how the picker wildcard came back
    twice. Asserting the attribute is absent makes that a test failure rather
    than a judgement call.
    """
    assert not hasattr(_mod.HumanInputLine(), attribute)


def test_typing_a_model_command_leaves_no_state_behind() -> None:
    """Recognition is gone; the line is still parsed and still cleared."""
    line = _mod.HumanInputLine()
    line.feed(b"/model opus\r")
    assert line.is_empty is True
    assert line.take_effort_submitted() is None


# ── A model change the human made opens no downgrade episode ────────────────


def test_a_human_model_change_is_never_restored(tmp_path: Path) -> None:
    """fable -> opus with nothing recorded: the human's own choice.

    Field defect this replaces -- the supervisor typed `/model fable` at a
    human who had just picked Opus, then drove effort to fable's floor and
    queued a `/compact`.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine)
    assert outcome.payload is None
    assert machine.export_state()["downgrade_episode"] is None
    # An elapsed quiet delay must not resurrect a restore either.
    later = _decide(sidecar_dir, machine, facts=_facts(_NOW + 10_000.0))
    assert later.decision_value != "would-model"


def test_a_picker_change_needs_no_keystrokes_to_be_respected(tmp_path: Path) -> None:
    """The picker types NOTHING -- and now needs to type nothing.

    This is the case every keystroke heuristic failed on: a bare `/model` plus
    arrow keys leaves no text for a parser to match. Attribution reads the
    platform's record instead, and there is none, so the choice stands.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    # No TickFacts field carries a model command any more -- the switch simply
    # appears in the next reading, exactly as the picker delivers it.
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    assert machine.export_state()["downgrade_episode"] is None


def test_an_unattributed_drop_says_why_nothing_was_done(tmp_path: Path) -> None:
    """Silence here is indistinguishable from a session never downgraded.

    Which is exactly how a disabled or failing `model_downgrade_recorder`
    would hide, so the NOOP reason names the missing signal.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    outcome = _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    assert outcome.noop_reason_log is not None
    assert "unattributed" in outcome.noop_reason_log
    assert "no restore" in outcome.noop_reason_log


def test_a_recorded_downgrade_still_restores(tmp_path: Path) -> None:
    """The one case the family exists for must keep working."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    write_attributed_downgrade(sidecar_dir, session_id=_SESSION)
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


def test_a_second_human_switch_after_a_recorded_one_is_not_covered_by_it(
    tmp_path: Path,
) -> None:
    """The record names ONE drop; it must not vouch for a later different one.

    fable -> opus is recorded (an episode opens); the human then goes on to
    sonnet. That second move matches no record, so nothing about it is the
    machine's business.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    write_attributed_downgrade(sidecar_dir, session_id=_SESSION)
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-sonnet-5", effort="high", ts=_NOW + 1.0)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 2.0))
    # opus -> sonnet did not start at fable, so no NEW episode; and the old
    # one keyed on opus cannot describe a session now sitting on sonnet.
    episode = machine.export_state()["downgrade_episode"]
    assert episode != f"{_SESSION}:sonnet"


def test_another_sessions_record_does_not_attribute_this_drop(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    write_attributed_downgrade(sidecar_dir, session_id="a-different-session")
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine)
    assert machine.export_state()["downgrade_episode"] is None


def test_decide_once_never_writes_to_the_global_worker_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unit test must never append to the LIVE session's worker error log."""
    calls: list[str] = []
    monkeypatch.setattr(_mod, "append_worker_error", lambda message: calls.append(message))
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    write_attributed_downgrade(sidecar_dir, session_id=_SESSION)
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine)
    assert calls == []


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


def test_manual_effort_cleared_by_an_observed_model_change(tmp_path: Path) -> None:
    """A spell is bounded by the family ON SCREEN, not by a typed command.

    Keying this on recognised keystrokes could not see a picker switch at all,
    so the latch survived into the next family and pinned effort to a choice
    made under the previous one.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    machine.note_manual_effort_command("low", now_wall=_NOW)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    assert machine.export_state()["manual_effort_active"] is None


def test_manual_effort_survives_a_reading_on_the_same_family(tmp_path: Path) -> None:
    """Only a CHANGE ends the spell -- a re-render of the same family does not."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    machine.note_manual_effort_command("low", now_wall=_NOW)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="low", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine, facts=_facts(_NOW + 1.0))
    assert machine.export_state()["manual_effort_active"] == "low"


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


def test_exported_state_carries_no_manual_model_fields() -> None:
    """The keystroke latches are gone from the host<->worker payload too.

    They rode in `export_state`, so a leftover key would keep a stale latch
    alive across every worker restart -- silently, and only in the field.
    """
    state = _machine().export_state()
    assert "manual_model_family" not in state
    assert "manual_model_ts" not in state
    assert "manual_selector_ts" not in state
    assert "manual_selector_session" not in state


def test_legacy_state_with_the_deleted_manual_fields_imports_cleanly() -> None:
    """A worker mid-upgrade can still be handed the OLD payload shape.

    The host and the worker are separate processes reloaded at different
    moments, so import must ignore keys it no longer knows rather than raise.
    """
    machine = _machine()
    legacy_state = machine.export_state()
    legacy_state["manual_model_family"] = "opus"
    legacy_state["manual_model_ts"] = _NOW
    legacy_state["manual_selector_ts"] = _NOW
    legacy_state["manual_selector_session"] = _SESSION
    fresh = _machine()
    fresh.import_state(legacy_state)
    fresh.arm_coupled_effort(session=_SESSION, family="fable")
    assert fresh.coupled_effort_pending == f"{_SESSION}:fable:low"


# ── TickFacts / worker JSON round-trip ───────────────────────────────────────


def test_tick_facts_effort_command_round_trips_through_json() -> None:
    facts = _mod.TickFacts(
        now_wall=_NOW,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
        human_effort_command="low",
    )
    line = _mod._facts_to_json(facts)
    restored = _mod._facts_from_json(line)
    assert restored.human_effort_command == "low"


def test_tick_facts_effort_command_defaults_to_none() -> None:
    facts = _mod.TickFacts(
        now_wall=_NOW,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
    )
    assert facts.human_effort_command is None


@pytest.mark.parametrize("field_name", ["human_model_command", "human_model_selector"])
def test_tick_facts_carries_no_model_command_field(field_name: str) -> None:
    """Nothing host-side may still be shipping a model keystroke to the worker."""
    facts = _mod.TickFacts(
        now_wall=_NOW,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
    )
    assert not hasattr(facts, field_name)


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


def test_a_fable_drop_all_the_way_to_sonnet_still_counts(tmp_path: Path) -> None:
    """The fallback target is opus today, but the rule keys on where the drop
    STARTED -- so a fallback to anything below fable is still covered."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    write_attributed_downgrade(
        sidecar_dir, session_id=_SESSION, original_family="fable", fallback_family="sonnet"
    )
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine)
    _write_sidecar(sidecar_dir, model_id="claude-sonnet-5", effort="high", ts=_NOW - 0.5)
    _decide(sidecar_dir, machine)
    assert machine.export_state()["downgrade_episode"] is not None
