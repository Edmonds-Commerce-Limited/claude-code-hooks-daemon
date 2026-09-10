"""The supervisor's OWN typed line is box content, and it is followed up.

Field incident (2026-09-09 22:52 -> 2026-09-10 06:40): an armed ``/goal``
was pasted into the input box while the session was mid-turn. The Enter that
followed did not submit it, the supervisor kept no record that it had typed
anything, and the line sat in the box for eight hours until the human pressed
Enter by hand. Nothing in ``decision.log`` distinguished "submitted" from
"never submitted" because the supervisor's own injections are kept out of the
input-box model on purpose (a human's line must never be typed over).

Two rules close that:

1. A submitted injection is REMEMBERED as the supervisor's own line. While it
   is pending, the subordinate families that would type MORE text (goal,
   goal-clear, standing-auth) defer rather than paste on top of it.
2. At the next lull (human idle, child quiet) the supervisor presses Enter
   again -- an Enter on an empty box is harmless, an Enter on its own stuck
   line submits it. A human Enter clears the record (whatever was in the box
   went), the session going busy after a resubmit clears it (it went), and a
   spent budget clears it (assume it went, log that we stopped).

Plus the goal cap is a ROLLING budget, not a lifetime one: a session that
lives for days met the five-goal lifetime cap and then silently ignored every
later plan flip.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 10_000.0
_SESSION = "own-line-sess"
_HEADER = (
    "🤖 [ccy-supervisor] automated goal — machine-generated, NOT a human "
    "instruction and NOT human authorisation for anything."
)
_JOINED = _HEADER + " — Work on Plan 00366 (title) at CLAUDE/Plan/00366-x until complete."


def _facts(
    now: float = _NOW,
    *,
    idle: bool = True,
    input_line_empty: bool = True,
    work_idle: bool = True,
    human_enter_pressed: bool = False,
) -> Any:
    return _mod.TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=work_idle,
        human_enter_pressed=human_enter_pressed,
    )


def _write_goal(sidecar_dir: Path, *, ts: float = _NOW - 5.0, text: str = _JOINED) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{_SESSION}.goal-intent"
    payload = {
        "ts": ts,
        "session_id": _SESSION,
        "plan_number": "00366",
        "rendered_lines": [text],
        "source": "status-flip",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _decide(sidecar_dir: Path, machine: Any, facts: Any, *, dry_run: bool = False) -> Any:
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=facts,
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
    )


def _machine_with_pending(sidecar_dir: Path) -> tuple[Any, Any]:
    """A machine that has just decided an armed /goal injection.

    The host's success-only bookkeeping (signal consumed, thrash guard set)
    is replayed by hand so the next tick does not simply re-decide the goal.
    """
    goal_path = _write_goal(sidecar_dir)
    machine = _mod.CompactStateMachine(_mod.CompactPolicy())
    outcome = _decide(sidecar_dir, machine, _facts())
    assert outcome.decision_value == "would-goal"
    goal_path.unlink()
    machine.mark_goal_injection(outcome.goal_line, now_wall=_NOW)
    return machine, outcome


class TestASubmittedInjectionIsRememberedAsTheSupervisorsOwnLine:
    def test_the_goal_decision_records_its_own_line(self, tmp_path: Path) -> None:
        machine, outcome = _machine_with_pending(tmp_path / "context-sidecar")
        assert machine.own_line_pending is True
        assert machine.own_line_text == outcome.payload
        assert outcome.machine_state["own_line_text"] == outcome.payload

    def test_a_dry_run_marker_is_not_remembered(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        _write_goal(sidecar_dir)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        outcome = _decide(sidecar_dir, machine, _facts(), dry_run=True)
        assert outcome.payload is not None
        assert machine.own_line_pending is False

    def test_a_raw_keypress_is_not_remembered(self) -> None:
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.mark_own_line_typed("\r", _NOW)
        assert machine.own_line_pending is False

    def test_the_record_round_trips_through_the_worker_state(self) -> None:
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.mark_own_line_typed("/goal x", _NOW)
        machine.mark_own_line_resubmit(_NOW + 20.0)
        exported = machine.export_state()
        assert exported["own_line_text"] == "/goal x"
        assert exported["own_line_ts"] == _NOW + 20.0
        assert exported["own_line_resubmits"] == 1
        fresh = _mod.CompactStateMachine(_mod.CompactPolicy())
        fresh.import_state(exported)
        assert fresh.own_line_pending is True
        assert fresh.own_line_resubmits == 1


class TestTheOwnLineIsFollowedUpWithAnEnterAtTheNextLull:
    def test_enter_is_pressed_once_the_line_has_aged_and_the_session_is_quiet(
        self, tmp_path: Path
    ) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        machine, _ = _machine_with_pending(sidecar_dir)
        later = _NOW + _mod._OWN_LINE_RESUBMIT_SECONDS
        outcome = _decide(sidecar_dir, machine, _facts(later))
        assert outcome.decision_value == "would-resubmit"
        assert outcome.payload == "\r"
        assert outcome.submit is False
        assert "own" in outcome.reason and "[enter]" in outcome.reason
        assert machine.own_line_resubmits == 1

    def test_no_enter_before_the_line_has_aged(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        machine, _ = _machine_with_pending(sidecar_dir)
        outcome = _decide(sidecar_dir, machine, _facts(_NOW + 1.0))
        assert outcome.payload is None
        assert machine.own_line_resubmits == 0

    def test_no_enter_while_the_child_is_still_working(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        machine, _ = _machine_with_pending(sidecar_dir)
        later = _NOW + _mod._OWN_LINE_RESUBMIT_SECONDS
        outcome = _decide(sidecar_dir, machine, _facts(later, work_idle=False))
        assert outcome.payload is None
        assert machine.own_line_pending is True

    def test_no_enter_while_the_human_is_typing(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        machine, _ = _machine_with_pending(sidecar_dir)
        later = _NOW + _mod._OWN_LINE_RESUBMIT_SECONDS
        outcome = _decide(sidecar_dir, machine, _facts(later, input_line_empty=False))
        assert outcome.payload is None
        assert machine.own_line_pending is True

    def test_a_human_enter_clears_the_record_without_a_keystroke(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        machine, _ = _machine_with_pending(sidecar_dir)
        later = _NOW + _mod._OWN_LINE_RESUBMIT_SECONDS
        outcome = _decide(sidecar_dir, machine, _facts(later, human_enter_pressed=True))
        assert outcome.payload is None
        assert machine.own_line_pending is False
        assert outcome.noop_reason_log is not None
        assert "human" in outcome.noop_reason_log

    def test_the_session_going_busy_after_the_enter_clears_the_record(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        machine, _ = _machine_with_pending(sidecar_dir)
        t1 = _NOW + _mod._OWN_LINE_RESUBMIT_SECONDS
        assert _decide(sidecar_dir, machine, _facts(t1)).decision_value == "would-resubmit"
        outcome = _decide(sidecar_dir, machine, _facts(t1 + 2.0, work_idle=False))
        assert outcome.payload is None
        assert machine.own_line_pending is False

    def test_the_budget_is_bounded_and_spending_it_is_logged(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        machine, _ = _machine_with_pending(sidecar_dir)
        t = _NOW
        for _ in range(_mod._MAX_OWN_LINE_RESUBMITS):
            t += _mod._OWN_LINE_RESUBMIT_SECONDS
            assert _decide(sidecar_dir, machine, _facts(t)).decision_value == "would-resubmit"
        t += _mod._OWN_LINE_RESUBMIT_SECONDS
        outcome = _decide(sidecar_dir, machine, _facts(t))
        assert outcome.payload is None
        assert machine.own_line_pending is False
        assert outcome.noop_reason_log is not None
        assert "budget" in outcome.noop_reason_log

    def test_the_second_enter_waits_for_a_fresh_interval(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        machine, _ = _machine_with_pending(sidecar_dir)
        t1 = _NOW + _mod._OWN_LINE_RESUBMIT_SECONDS
        assert _decide(sidecar_dir, machine, _facts(t1)).decision_value == "would-resubmit"
        outcome = _decide(sidecar_dir, machine, _facts(t1 + 2.0))
        assert outcome.payload is None
        assert machine.own_line_resubmits == 1


class TestTheOwnLineBlocksTypingMoreTextOnTopOfIt:
    def test_a_new_goal_defers_while_the_own_line_is_pending(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        machine, _ = _machine_with_pending(sidecar_dir)
        second = _write_goal(sidecar_dir, text=_JOINED + " (second)")
        outcome = _decide(sidecar_dir, machine, _facts(_NOW + 2.0))
        assert outcome.payload is None
        assert outcome.noop_reason_log is not None
        assert "own" in outcome.noop_reason_log
        assert second.exists()

    def test_the_deferred_goal_injects_once_the_own_line_is_cleared(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        machine, _ = _machine_with_pending(sidecar_dir)
        _write_goal(sidecar_dir, text=_JOINED + " (second)")
        # The human's Enter empties the box, so the same tick may type the
        # deferred goal straight away.
        outcome = _decide(sidecar_dir, machine, _facts(_NOW + 2.0, human_enter_pressed=True))
        assert outcome.decision_value == "would-goal"
        assert machine.own_line_text == outcome.payload


class TestTheHumanEnterIsRecognisedByTheWorker:
    def test_the_line_model_reports_an_enter_once(self) -> None:
        line = _mod.HumanInputLine()
        line.feed(b"hello\r")
        assert line.take_enter_pressed() is True
        assert line.take_enter_pressed() is False

    def test_an_enter_on_an_empty_box_still_counts(self) -> None:
        line = _mod.HumanInputLine()
        line.feed(b"\r")
        assert line.take_enter_pressed() is True

    def test_ctrl_c_and_ctrl_u_are_not_an_enter(self) -> None:
        line = _mod.HumanInputLine()
        line.feed(b"abc\x15\x03")
        assert line.take_enter_pressed() is False

    def test_facts_json_carries_the_flag_and_defaults_it(self) -> None:
        facts = _facts(human_enter_pressed=True)
        parsed = _mod._facts_from_json(_mod._facts_to_json(facts))
        assert parsed.human_enter_pressed is True
        legacy = json.loads(_mod._facts_to_json(_facts()))
        del legacy["human_enter_pressed"]
        assert _mod._facts_from_json(json.dumps(legacy)).human_enter_pressed is False


class TestTheGoalCapIsARollingBudget:
    def test_five_recent_goals_reach_the_cap(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        _write_goal(sidecar_dir)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        for _ in range(_mod._MAX_GOAL_INJECTIONS):
            machine.mark_goal_injection("x", now_wall=_NOW - 60.0)
        outcome = _decide(sidecar_dir, machine, _facts())
        assert outcome.payload is None
        assert "cap" in outcome.noop_reason_log

    def test_old_goals_fall_out_of_the_window(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        _write_goal(sidecar_dir)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        stale = _NOW - _mod._GOAL_CAP_WINDOW_SECONDS - 1.0
        for _ in range(_mod._MAX_GOAL_INJECTIONS):
            machine.mark_goal_injection("x", now_wall=stale)
        outcome = _decide(sidecar_dir, machine, _facts())
        assert outcome.decision_value == "would-goal"

    def test_the_window_round_trips(self) -> None:
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.mark_goal_injection("x", now_wall=_NOW)
        exported = machine.export_state()
        assert exported["goal_injection_ts"] == [_NOW]
        fresh = _mod.CompactStateMachine(_mod.CompactPolicy())
        fresh.import_state(exported)
        assert fresh.goal_injections_within(_mod._GOAL_CAP_WINDOW_SECONDS, _NOW) == 1
