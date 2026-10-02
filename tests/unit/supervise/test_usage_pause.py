"""Plan 00479 Task 4.5 -- the supervisor's behaviour while a usage pause is recorded.

The daemon's usage gate writes ``<session>.usage-paused`` (see
``claude_code_hooks_daemon.utils.usage_pause``). While that record is live the
supervisor injects exactly ONE ``/compact`` -- once the session has stopped --
telling the session to do nothing until its resume cron fires, and injects no
``continue``, ``/goal`` or any other nudge. Lifting the pause (the record
disappearing) restores normal behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.utils import usage_pause
from claude_code_hooks_daemon.utils.usage_pause import UsagePause
from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()

_SESSION = "fg"
_NOW = 1_800_000_000.0  # 2027-01-15 08:00:00 UTC
_RESUME_AT = _NOW + 3 * 3600.0  # 2027-01-15 11:00:00 UTC
_RESUME_TEXT = "2027-01-15 11:00 UTC"


def _write_pause(sidecar_dir: Path, **overrides: Any) -> UsagePause:
    fields: dict[str, Any] = {
        "session_id": _SESSION,
        "paused_at": _NOW - 60.0,
        "resume_at": _RESUME_AT,
        "window": usage_pause.WINDOW_FIVE_HOUR,
        "used_percentage": 93.0,
        "ceiling": 90.0,
        "reason": "five_hour window at 93% (ceiling 90%)",
    }
    fields.update(overrides)
    pause = UsagePause(**fields)
    # The daemon writes under <untracked>/context-sidecar; the supervisor is
    # handed that directory itself.
    usage_pause.write_usage_pause(sidecar_dir.parent, pause)
    return pause


def _write_red_sidecar(sidecar_dir: Path, *, ts: float = _NOW) -> None:
    """A context reading that, absent a pause, makes the supervisor compact."""
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    (sidecar_dir / f"{_SESSION}.json").write_text(
        json.dumps(
            {
                "red": True,
                "critical": False,
                "compact_urgent": True,
                "tier": "urgent",
                "pct": 80.0,
                "session_id": _SESSION,
                "ts": ts,
                "seq": 1,
                "writer_pid": 1,
                "compacting": False,
            }
        ),
        encoding="utf-8",
    )


def _facts(
    *, now: float = _NOW, idle: bool = True, work_idle: bool = True, input_line_empty: bool = True
) -> Any:
    return _mod.TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=work_idle,
    )


def _decide(
    sidecar_dir: Path,
    machine: Any,
    *,
    facts: Any | None = None,
    dry_run: bool = False,
    own_sessions: frozenset[str] | None = None,
) -> Any:
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=facts or _facts(),
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
        own_sessions=own_sessions,
    )


@pytest.fixture
def sidecar_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "context-sidecar"
    directory.mkdir()
    return directory


@pytest.fixture
def machine() -> Any:
    return _mod.CompactStateMachine(_mod.CompactPolicy())


class TestPinnedToTheDaemonRecord:
    """The supervisor is stdlib-only and keeps its own copies; they must not drift."""

    def test_suffix(self) -> None:
        assert _mod._USAGE_PAUSE_SUFFIX == usage_pause.SIGNAL_SUFFIX

    def test_field_names(self) -> None:
        assert _mod._USAGE_PAUSE_FIELDS == (
            usage_pause.FIELD_SESSION_ID,
            usage_pause.FIELD_PAUSED_AT,
            usage_pause.FIELD_RESUME_AT,
            usage_pause.FIELD_WINDOW,
            usage_pause.FIELD_USED_PERCENTAGE,
            usage_pause.FIELD_CEILING,
            usage_pause.FIELD_REASON,
        )

    def test_windows(self) -> None:
        assert _mod._USAGE_PAUSE_WINDOWS == usage_pause.WINDOWS

    def test_grace(self) -> None:
        assert _mod._USAGE_PAUSE_GRACE_SECONDS == usage_pause.PAUSE_GRACE_SECONDS

    def test_max_span(self) -> None:
        assert _mod._USAGE_PAUSE_MAX_SPAN_SECONDS == usage_pause.MAX_PAUSE_SPAN_SECONDS


class TestLoadUsagePause:
    def test_reads_a_daemon_written_record(self, sidecar_dir: Path) -> None:
        written = _write_pause(sidecar_dir)
        record = _mod.load_usage_pause(sidecar_dir, now=_NOW, own_sessions=None)
        assert record is not None
        assert record.session_id == written.session_id
        assert record.paused_at == written.paused_at
        assert record.resume_at == written.resume_at
        assert record.window == written.window
        assert record.reason == written.reason

    def test_no_record_means_no_pause(self, sidecar_dir: Path) -> None:
        assert _mod.load_usage_pause(sidecar_dir, now=_NOW, own_sessions=None) is None

    def test_missing_directory_means_no_pause(self, tmp_path: Path) -> None:
        assert _mod.load_usage_pause(tmp_path / "absent", now=_NOW, own_sessions=None) is None

    def test_a_foreign_session_is_not_this_sessions_pause(self, sidecar_dir: Path) -> None:
        _write_pause(sidecar_dir, session_id="elsewhere")
        own = frozenset({_SESSION})
        assert _mod.load_usage_pause(sidecar_dir, now=_NOW, own_sessions=own) is None

    def test_an_empty_own_session_set_acts_on_nothing(self, sidecar_dir: Path) -> None:
        _write_pause(sidecar_dir)
        assert _mod.load_usage_pause(sidecar_dir, now=_NOW, own_sessions=frozenset()) is None

    def test_expired_record_is_no_pause(self, sidecar_dir: Path) -> None:
        _write_pause(sidecar_dir)
        late = _RESUME_AT + usage_pause.PAUSE_GRACE_SECONDS + 1
        assert _mod.load_usage_pause(sidecar_dir, now=late, own_sessions=None) is None

    def test_future_dated_record_is_no_pause(self, sidecar_dir: Path) -> None:
        _write_pause(sidecar_dir, paused_at=_NOW + 500.0)
        assert _mod.load_usage_pause(sidecar_dir, now=_NOW, own_sessions=None) is None

    @pytest.mark.parametrize(
        "mutation",
        [
            {"window": "monthly"},
            {"window": 5},
            {"resume_at": "soon"},
            {"resume_at": True},
            {"used_percentage": None},
            {"reason": 3},
            {"session_id": None},
        ],
    )
    def test_malformed_field_is_no_pause(self, sidecar_dir: Path, mutation: dict[str, Any]) -> None:
        path = _write_pause_path(sidecar_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(mutation)
        path.write_text(json.dumps(data), encoding="utf-8")
        assert _mod.load_usage_pause(sidecar_dir, now=_NOW, own_sessions=None) is None

    def test_a_record_pausing_for_longer_than_the_cap_is_no_pause(self, sidecar_dir: Path) -> None:
        path = _write_pause_path(sidecar_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["resume_at"] = data["paused_at"] + usage_pause.MAX_PAUSE_SPAN_SECONDS + 1
        path.write_text(json.dumps(data), encoding="utf-8")
        assert _mod.load_usage_pause(sidecar_dir, now=_NOW, own_sessions=None) is None

    def test_a_record_at_the_cap_still_counts(self, sidecar_dir: Path) -> None:
        path = _write_pause_path(sidecar_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["resume_at"] = data["paused_at"] + usage_pause.MAX_PAUSE_SPAN_SECONDS
        path.write_text(json.dumps(data), encoding="utf-8")
        assert _mod.load_usage_pause(sidecar_dir, now=_NOW, own_sessions=None) is not None

    def test_resume_not_after_pause_is_no_pause(self, sidecar_dir: Path) -> None:
        path = _write_pause_path(sidecar_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["resume_at"] = data["paused_at"]
        path.write_text(json.dumps(data), encoding="utf-8")
        assert _mod.load_usage_pause(sidecar_dir, now=_NOW, own_sessions=None) is None

    @pytest.mark.parametrize("content", ["", "nope", "[]", "null", "42"])
    def test_unreadable_record_is_no_pause(self, sidecar_dir: Path, content: str) -> None:
        (sidecar_dir / f"{_SESSION}.usage-paused").write_text(content, encoding="utf-8")
        assert _mod.load_usage_pause(sidecar_dir, now=_NOW, own_sessions=None) is None

    def test_one_bad_record_does_not_hide_a_good_one(self, sidecar_dir: Path) -> None:
        (sidecar_dir / "bad.usage-paused").write_text("nope", encoding="utf-8")
        _write_pause(sidecar_dir)
        assert _mod.load_usage_pause(sidecar_dir, now=_NOW, own_sessions=None) is not None

    def test_the_latest_pause_wins(self, sidecar_dir: Path) -> None:
        _write_pause(sidecar_dir, session_id="a", paused_at=_NOW - 500.0)
        _write_pause(sidecar_dir, session_id="b", paused_at=_NOW - 10.0)
        record = _mod.load_usage_pause(sidecar_dir, now=_NOW, own_sessions=None)
        assert record is not None
        assert record.session_id == "b"


def _write_pause_path(sidecar_dir: Path) -> Path:
    _write_pause(sidecar_dir)
    return sidecar_dir / f"{_SESSION}.usage-paused"


class TestPauseCompact:
    def test_idle_paused_session_gets_one_compact_that_does_not_continue(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_pause(sidecar_dir)
        outcome = _decide(sidecar_dir, machine)
        assert outcome.decision_value == "would-compact"
        assert outcome.payload is not None
        assert outcome.payload.startswith("/compact ")
        assert outcome.submit is True

    def test_instruction_names_the_resume_time_and_says_do_nothing(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_pause(sidecar_dir)
        payload = _decide(sidecar_dir, machine).payload
        assert payload is not None
        assert _RESUME_TEXT in payload
        assert "resume cron" in payload
        assert "do nothing" in payload.lower()
        assert "continue the work" not in payload.lower()

    def test_the_compact_carries_the_supervisor_marker_the_daemon_attributes(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_pause(sidecar_dir)
        payload = _decide(sidecar_dir, machine).payload
        assert payload is not None
        instructions = payload.removeprefix("/compact ")
        assert instructions.startswith(_mod._BOT_PREFIX)

    def test_decision_reason_names_the_pause(self, sidecar_dir: Path, machine: Any) -> None:
        _write_pause(sidecar_dir)
        reason = _decide(sidecar_dir, machine).reason
        assert "usage pause" in reason
        assert _RESUME_TEXT in reason

    def test_exactly_one_compact_per_pause(self, sidecar_dir: Path, machine: Any) -> None:
        _write_pause(sidecar_dir)
        first = _decide(sidecar_dir, machine)
        assert first.payload is not None
        for step in range(1, 6):
            again = _decide(sidecar_dir, machine, facts=_facts(now=_NOW + step * 30.0))
            assert again.payload is None
            assert again.decision_value == "noop"

    def test_the_latch_survives_the_worker_state_round_trip(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_pause(sidecar_dir)
        first = _decide(sidecar_dir, machine)
        fresh = _mod.CompactStateMachine(_mod.CompactPolicy())
        facts = _mod.TickFacts(
            now_wall=_NOW + 30.0,
            idle=True,
            input_line_empty=True,
            human_compact_submitted=False,
            work_idle=True,
            machine_state=first.machine_state,
        )
        assert _decide(sidecar_dir, fresh, facts=facts).payload is None

    def test_waits_while_the_session_is_still_working(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_pause(sidecar_dir)
        busy = _decide(sidecar_dir, machine, facts=_facts(work_idle=False))
        assert busy.payload is None
        assert busy.noop_reason_log is not None
        assert "usage pause" in busy.noop_reason_log
        assert _decide(sidecar_dir, machine).payload is not None

    def test_waits_while_a_human_is_typing(self, sidecar_dir: Path, machine: Any) -> None:
        _write_pause(sidecar_dir)
        assert _decide(sidecar_dir, machine, facts=_facts(idle=False)).payload is None

    def test_defers_while_the_input_box_holds_text_and_says_so(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_pause(sidecar_dir)
        outcome = _decide(sidecar_dir, machine, facts=_facts(input_line_empty=False))
        assert outcome.payload is None
        assert outcome.deferred_log is not None
        assert "usage-pause compact" in outcome.deferred_log
        assert _decide(sidecar_dir, machine).payload is not None

    def test_dry_run_injects_a_visible_marker_not_a_real_compact_and_latches(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_pause(sidecar_dir)
        first = _decide(sidecar_dir, machine, dry_run=True)
        assert first.payload is not None
        assert not first.payload.startswith("/compact")
        assert "dry-run" in first.payload
        assert _decide(sidecar_dir, machine, dry_run=True).payload is None

    def test_a_pause_that_is_not_ours_changes_nothing(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_pause(sidecar_dir, session_id="elsewhere")
        outcome = _decide(sidecar_dir, machine, own_sessions=frozenset({_SESSION}))
        assert outcome.payload is None
        assert "usage pause" not in outcome.reason
        assert "usage pause" not in (outcome.noop_reason_log or "")


class TestNoNudgesWhilePaused:
    def test_a_red_context_does_not_trigger_the_ordinary_compact(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_red_sidecar(sidecar_dir)
        _write_pause(sidecar_dir)
        first = _decide(sidecar_dir, machine)
        assert first.payload is not None
        assert "continue the work" not in first.payload.lower()
        for step in range(1, 4):
            now = _NOW + step * 30.0
            _write_red_sidecar(sidecar_dir, ts=now)
            again = _decide(sidecar_dir, machine, facts=_facts(now=now))
            assert again.payload is None

    def test_no_continue_after_the_pause_compact_runs(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_pause(sidecar_dir)
        _decide(sidecar_dir, machine)
        # The daemon's PreCompact record for the compaction the supervisor just typed.
        (sidecar_dir / f"{_SESSION}.compacting").write_text(
            json.dumps(
                {
                    "ts": _NOW + 5.0,
                    "session_id": _SESSION,
                    "trigger": "manual",
                    "origin": "supervisor",
                }
            ),
            encoding="utf-8",
        )
        for step in range(1, 5):
            outcome = _decide(sidecar_dir, machine, facts=_facts(now=_NOW + 10.0 * step))
            assert outcome.payload is None
            assert outcome.decision_value == "noop"

    def test_a_pending_goal_is_not_typed(self, sidecar_dir: Path, machine: Any) -> None:
        _write_pause(sidecar_dir)
        _decide(sidecar_dir, machine)
        (sidecar_dir / f"{_SESSION}.goal-intent").write_text(
            json.dumps(
                {
                    "ts": _NOW,
                    "session_id": _SESSION,
                    "rendered_lines": [_mod._GOAL_HEADER_TEXT],
                }
            ),
            encoding="utf-8",
        )
        outcome = _decide(sidecar_dir, machine, facts=_facts(now=_NOW + 30.0))
        assert outcome.payload is None
        assert outcome.consume_signal_path is None

    def test_an_await_in_flight_is_dropped_so_no_continue_follows(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        machine.state = _mod.SupervisorState.AWAIT_COMPACTING
        _write_pause(sidecar_dir)
        outcome = _decide(sidecar_dir, machine)
        assert outcome.payload is None
        assert machine.state is _mod.SupervisorState.MONITOR
        # The next tick may now compact: the host's stale-suppression guard
        # (host already awaiting) cannot swallow the latch.
        assert _decide(sidecar_dir, machine, facts=_facts(now=_NOW + 30.0)).payload is not None

    def test_every_paused_tick_is_noop_after_the_compact_and_says_why(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_pause(sidecar_dir)
        _decide(sidecar_dir, machine)
        outcome = _decide(sidecar_dir, machine, facts=_facts(now=_NOW + 30.0))
        assert outcome.noop_reason_log is not None
        assert "usage pause" in outcome.noop_reason_log
        assert _RESUME_TEXT in outcome.noop_reason_log


class TestPauseLifted:
    def test_normal_behaviour_resumes_when_the_record_is_cleared(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_red_sidecar(sidecar_dir)
        _write_pause(sidecar_dir)
        _decide(sidecar_dir, machine)
        usage_pause.clear_usage_pause(sidecar_dir.parent, _SESSION)
        _write_red_sidecar(sidecar_dir, ts=_NOW + 60.0)  # a fresh reading, as in a live session
        outcome = _decide(sidecar_dir, machine, facts=_facts(now=_NOW + 60.0))
        assert outcome.decision_value == "would-compact"
        assert outcome.payload is not None
        assert "continue the work" in outcome.payload.lower()

    def test_the_lift_is_logged_once(self, sidecar_dir: Path, machine: Any) -> None:
        _write_pause(sidecar_dir)
        _decide(sidecar_dir, machine)
        usage_pause.clear_usage_pause(sidecar_dir.parent, _SESSION)
        lifted = _decide(sidecar_dir, machine, facts=_facts(now=_NOW + 60.0))
        assert lifted.noop_reason_log is not None
        assert "usage pause lifted" in lifted.noop_reason_log
        after = _decide(sidecar_dir, machine, facts=_facts(now=_NOW + 90.0))
        assert "usage pause lifted" not in (after.noop_reason_log or "")

    def test_a_later_pause_gets_its_own_compact(self, sidecar_dir: Path, machine: Any) -> None:
        _write_pause(sidecar_dir)
        assert _decide(sidecar_dir, machine).payload is not None
        usage_pause.clear_usage_pause(sidecar_dir.parent, _SESSION)
        _decide(sidecar_dir, machine, facts=_facts(now=_NOW + 60.0))
        _write_pause(sidecar_dir, paused_at=_NOW + 100.0, resume_at=_NOW + 9000.0)
        second = _decide(sidecar_dir, machine, facts=_facts(now=_NOW + 120.0))
        assert second.payload is not None
        assert second.payload.startswith("/compact ")

    def test_an_expired_record_lifts_the_pause_by_itself(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_pause(sidecar_dir)
        _decide(sidecar_dir, machine)
        late = _RESUME_AT + usage_pause.PAUSE_GRACE_SECONDS + 5.0
        lifted = _decide(sidecar_dir, machine, facts=_facts(now=late))
        assert lifted.noop_reason_log is not None
        assert "usage pause lifted" in lifted.noop_reason_log


class TestMachineState:
    def test_latch_round_trips_through_export_and_import(self, machine: Any) -> None:
        machine.mark_pause_compacted(123.0)
        clone = _mod.CompactStateMachine(_mod.CompactPolicy())
        clone.import_state(machine.export_state())
        assert clone.pause_compacted_for == 123.0

    def test_a_state_without_the_key_keeps_the_current_latch(self, machine: Any) -> None:
        machine.mark_pause_compacted(5.0)
        machine.import_state({"state": "monitor"})
        assert machine.pause_compacted_for == 5.0

    def test_clear_forgets_the_latch(self, machine: Any) -> None:
        machine.mark_pause_compacted(5.0)
        machine.clear_pause_compacted()
        assert machine.pause_compacted_for is None
