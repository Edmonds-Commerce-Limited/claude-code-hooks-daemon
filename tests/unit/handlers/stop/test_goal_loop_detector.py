"""Tests for the goal-loop detector Stop handler (Plan 00501 Tasks 6.1 and 6.2).

The handler only observes: it reads the transcript from a per-session
checkpoint, feeds the cycle ring, and appends near-miss, would-enter and
loop-reset transitions to the session-mode transition log. Every failure is a
named WARNING and the Stop is always allowed.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from tests.support.autonomy import pin_session_modes

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.goal_clear_attribution import (
    ATTRIBUTED_CLEARS_FILENAME,
    record_path,
)
from claude_code_hooks_daemon.core.goal_loop import FingerprintError, option_problems
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.session_mode_log import ModeTransition, TransitionAction
from claude_code_hooks_daemon.core.session_mode_registry import NoticeKind, SessionModeRegistry
from claude_code_hooks_daemon.handlers.stop.goal_loop_detector import (
    MAX_TRACKED_SESSIONS,
    GoalLoopDetectorHandler,
)
from claude_code_hooks_daemon.utils.session_modes import ModeLabel
from claude_code_hooks_daemon.utils.session_signal_paths import SIGNAL_SUBDIR

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "goal_loop"
SESSION = "sess-goal-loop"


def _stamp(second: int) -> str:
    minutes, seconds = divmod(second, 60)
    return f"2026-01-05T10:{minutes:02d}:{seconds:02d}.000Z"


def _stop(second: int, text: str = "STOPPING BECAUSE: blocked on the fixture.") -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
            "timestamp": _stamp(second),
        }
    )


def _unmet(second: int) -> str:
    return json.dumps(
        {
            "type": "attachment",
            "attachment": {"type": "goal_status", "met": False, "condition": "done"},
            "timestamp": _stamp(second),
        }
    )


def _human(second: int) -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {"role": "user", "content": "please carry on with the plan"},
            "timestamp": _stamp(second),
        }
    )


def _cycle(second: int) -> list[str]:
    return [_stop(second), _unmet(second + 1)]


def _append_lines(path: Path, lines: list[str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("".join(f"{line}\n" for line in lines))


class _Recorder:
    """Collects appended transitions in place of the transition log."""

    def __init__(self) -> None:
        self.transitions: list[ModeTransition] = []

    def __call__(self, transition: ModeTransition) -> None:
        self.transitions.append(transition)

    def actions(self) -> list[TransitionAction]:
        return [t.action for t in self.transitions]


@pytest.fixture
def recorder() -> _Recorder:
    return _Recorder()


@pytest.fixture
def handler(recorder: _Recorder) -> GoalLoopDetectorHandler:
    detector = GoalLoopDetectorHandler()
    detector._fingerprint_repo = lambda: "fp-stable"
    detector._append_transition = recorder
    return detector


def _input(transcript: Path | None, session_id: str = SESSION) -> dict[str, Any]:
    hook_input: dict[str, Any] = {"hook_event_name": "Stop", "session_id": session_id}
    if transcript is not None:
        hook_input["transcript_path"] = str(transcript)
    return hook_input


class TestIdentity:
    def test_identity_and_ordering(self, handler: GoalLoopDetectorHandler) -> None:
        assert handler.handler_id == HandlerID.GOAL_LOOP_DETECTOR
        assert handler.priority == Priority.GOAL_LOOP_DETECTOR == 5
        assert handler.terminal is False
        assert handler.scope is HandlerScope.MAIN

    def test_matches_every_stop(self, handler: GoalLoopDetectorHandler) -> None:
        assert handler.matches(_input(None)) is True

    def test_validate_options_is_the_core_option_check(self) -> None:
        options = {"mode": "halt", "cycle_threshold": 0}
        assert GoalLoopDetectorHandler.validate_options(options) == option_problems(options)
        assert set(GoalLoopDetectorHandler.validate_options(options)) == {
            "mode",
            "cycle_threshold",
        }

    def test_default_options(self, handler: GoalLoopDetectorHandler) -> None:
        assert handler._mode == "observe"
        assert handler._cycle_threshold == 3
        assert handler._declared_cycle_threshold == 2
        assert handler._window_minutes == 30
        assert handler._blocked_hours == 4

    def test_enabled_by_default(self, handler: GoalLoopDetectorHandler) -> None:
        assert handler.get_default_enabled() is True


class TestAcceptanceTests:
    def test_every_case_runs_where_the_handler_fires(
        self, handler: GoalLoopDetectorHandler
    ) -> None:
        # The handler is MAIN-scoped: run from a sub-agent it never fires, and
        # an ALLOW there would pass whatever the handler did.
        cases = handler.get_acceptance_tests()
        assert cases
        assert all(case.requires_main_thread for case in cases)

    def test_each_case_expects_what_the_handler_decides(
        self, handler: GoalLoopDetectorHandler
    ) -> None:
        for case in handler.get_acceptance_tests():
            assert handler.handle(case.hook_input).decision == case.expected_decision


class TestDetection:
    def test_fixture_loop_logs_would_enter_and_allows(
        self, handler: GoalLoopDetectorHandler, recorder: _Recorder, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        result = handler.handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert recorder.actions() == [TransitionAction.WOULD_ENTER]
        transition = recorder.transitions[0]
        assert transition.label is ModeLabel.GOAL_BLOCKED
        assert transition.session_id == SESSION
        assert "cycles=3" in transition.evidence
        assert "fingerprint=fp-stable" in transition.evidence
        assert "mode=observe" in transition.evidence

    def test_incremental_reads_log_near_miss_then_would_enter(
        self, handler: GoalLoopDetectorHandler, recorder: _Recorder, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_human(0), *_cycle(10)])
        handler.handle(_input(transcript))
        assert recorder.actions() == []
        _append_lines(transcript, _cycle(20))
        handler.handle(_input(transcript))
        assert recorder.actions() == [TransitionAction.NEAR_MISS]
        _append_lines(transcript, _cycle(30))
        handler.handle(_input(transcript))
        assert recorder.actions() == [TransitionAction.NEAR_MISS, TransitionAction.WOULD_ENTER]

    def test_a_stop_with_no_new_cycle_logs_nothing(
        self, handler: GoalLoopDetectorHandler, recorder: _Recorder, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [*_cycle(10), *_cycle(20)])
        handler.handle(_input(transcript))
        _append_lines(transcript, [_stop(40)])
        handler.handle(_input(transcript))
        assert recorder.actions() == [TransitionAction.NEAR_MISS]

    def test_declared_stops_use_the_declared_threshold(
        self, handler: GoalLoopDetectorHandler, recorder: _Recorder, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "declared_stops.jsonl", transcript)
        handler.handle(_input(transcript))
        assert TransitionAction.WOULD_ENTER in recorder.actions()

    def test_configured_threshold_is_honoured(
        self, handler: GoalLoopDetectorHandler, recorder: _Recorder, tmp_path: Path
    ) -> None:
        handler._cycle_threshold = 5
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        handler.handle(_input(transcript))
        assert recorder.actions() == []

    def test_sessions_are_tracked_separately(
        self, handler: GoalLoopDetectorHandler, recorder: _Recorder, tmp_path: Path
    ) -> None:
        first = tmp_path / "a.jsonl"
        second = tmp_path / "b.jsonl"
        _append_lines(first, [*_cycle(10), *_cycle(20)])
        _append_lines(second, _cycle(10))
        handler.handle(_input(first, "sess-a"))
        handler.handle(_input(second, "sess-b"))
        assert [t.session_id for t in recorder.transitions] == ["sess-a"]


class TestResets:
    def test_human_prompt_logs_a_loop_reset(
        self, handler: GoalLoopDetectorHandler, recorder: _Recorder, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [*_cycle(10), *_cycle(20)])
        handler.handle(_input(transcript))
        _append_lines(transcript, [_human(30)])
        handler.handle(_input(transcript))
        reset = recorder.transitions[-1]
        assert reset.action is TransitionAction.LOOP_RESET
        assert reset.detail == "human-prompt"
        assert "dropped=2" in reset.evidence

    def test_goal_cleared_fixture_logs_a_loop_reset(
        self, handler: GoalLoopDetectorHandler, recorder: _Recorder, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "goal_cleared.jsonl", transcript)
        handler.handle(_input(transcript))
        details = [
            t.detail for t in recorder.transitions if t.action is TransitionAction.LOOP_RESET
        ]
        assert details == ["goal-cleared"]

    def test_repo_change_logs_a_loop_reset(
        self, handler: GoalLoopDetectorHandler, recorder: _Recorder, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [*_cycle(10), *_cycle(20)])
        handler.handle(_input(transcript))
        handler._fingerprint_repo = lambda: "fp-changed"
        _append_lines(transcript, _cycle(30))
        handler.handle(_input(transcript))
        assert recorder.actions() == [TransitionAction.NEAR_MISS, TransitionAction.LOOP_RESET]
        assert recorder.transitions[-1].detail == "repo-change"


class TestStandDowns:
    def test_missing_transcript_path_allows_at_info(
        self,
        handler: GoalLoopDetectorHandler,
        recorder: _Recorder,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO):
            result = handler.handle(_input(None))
        assert result.decision == Decision.ALLOW
        assert recorder.transitions == []
        assert any(
            r.levelno == logging.INFO and "no transcript_path" in r.getMessage()
            for r in caplog.records
        )

    def test_missing_session_id_allows(
        self, handler: GoalLoopDetectorHandler, recorder: _Recorder, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        result = handler.handle(_input(transcript, session_id=""))
        assert result.decision == Decision.ALLOW
        assert recorder.transitions == []

    def test_unreadable_transcript_is_a_named_warning(
        self,
        handler: GoalLoopDetectorHandler,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        missing = tmp_path / "absent.jsonl"
        with caplog.at_level(logging.WARNING):
            result = handler.handle(_input(missing))
        assert result.decision == Decision.ALLOW
        assert any(
            "goal-loop detector: transcript unreadable" in r.getMessage()
            and str(missing) in r.getMessage()
            for r in caplog.records
        )

    def test_invalid_checkpoint_re_anchors_at_eof(
        self,
        handler: GoalLoopDetectorHandler,
        recorder: _Recorder,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [*_cycle(10), *_cycle(20), *_cycle(30)])
        handler.handle(_input(transcript))
        before = len(recorder.transitions)
        transcript.write_text("", encoding="utf-8")
        _append_lines(transcript, _cycle(40))
        with caplog.at_level(logging.WARNING):
            result = handler.handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert recorder.transitions[before:] == []
        assert any(
            "checkpoint invalid, re-anchored at EOF" in r.getMessage() for r in caplog.records
        )
        # The anchor sits at EOF: the cycle already on disk is never counted, and
        # only what is appended after it is. The ring restarted at the first
        # would-enter, so two appended cycles are a near miss, not a third cycle.
        _append_lines(transcript, [*_cycle(50), *_cycle(60)])
        handler.handle(_input(transcript))
        assert recorder.actions()[before:] == [TransitionAction.NEAR_MISS]
        _append_lines(transcript, _cycle(70))
        handler.handle(_input(transcript))
        assert recorder.actions()[before:] == [
            TransitionAction.NEAR_MISS,
            TransitionAction.WOULD_ENTER,
        ]
        assert "cycles=3" in recorder.transitions[-1].evidence

    def test_fingerprint_failure_is_a_named_warning_and_skips_the_assessment(
        self,
        handler: GoalLoopDetectorHandler,
        recorder: _Recorder,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def _fail() -> str:
            raise FingerprintError("git status failed: boom")

        handler._fingerprint_repo = _fail
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        with caplog.at_level(logging.WARNING):
            result = handler.handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert recorder.transitions == []
        assert any(
            "goal-loop detector: fingerprint failed: git status failed: boom" in r.getMessage()
            for r in caplog.records
        )

    @pytest.mark.parametrize("error", [OSError("disk full"), RuntimeError("no context")])
    def test_append_failure_is_a_named_warning(
        self,
        handler: GoalLoopDetectorHandler,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        error: Exception,
    ) -> None:
        def _fail(transition: ModeTransition) -> None:
            raise error

        handler._append_transition = _fail
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        with caplog.at_level(logging.WARNING):
            result = handler.handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert any(
            "goal-loop detector: transition not logged" in r.getMessage() for r in caplog.records
        )

    def test_tracked_sessions_are_bounded(
        self, handler: GoalLoopDetectorHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_human(0)])
        for index in range(MAX_TRACKED_SESSIONS + 3):
            handler.handle(_input(transcript, f"sess-{index}"))
        assert len(handler._sessions) == MAX_TRACKED_SESSIONS
        assert "sess-0" not in handler._sessions
        assert f"sess-{MAX_TRACKED_SESSIONS + 2}" in handler._sessions


@pytest.fixture
def modes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SessionModeRegistry:
    return pin_session_modes(monkeypatch, tmp_path / "untracked")


@pytest.fixture
def clear_goal() -> MagicMock:
    return MagicMock(return_value=True)


@pytest.fixture
def actor(
    handler: GoalLoopDetectorHandler, modes: SessionModeRegistry, clear_goal: MagicMock
) -> GoalLoopDetectorHandler:
    """The handler in act mode on a real registry, with a counting goal clear."""
    handler._mode = "act"
    handler._registry = lambda: modes
    handler._clear_goal = clear_goal
    return handler


def _registry_actions(modes: SessionModeRegistry) -> list[tuple[TransitionAction, str]]:
    log = modes.transition_log
    assert log is not None
    return [(t.action, t.evidence) for t in log.recent(50, session_id=SESSION)]


def _labels(modes: SessionModeRegistry) -> list[ModeLabel]:
    return [entry.label for entry in modes.active(SESSION)]


class TestActMode:
    """Act mode enters GOAL_BLOCKED once, queues the one-time line, and exits (Tasks 6.3, 6.4)."""

    def test_act_enters_clears_once_and_queues_one_notice(
        self,
        actor: GoalLoopDetectorHandler,
        modes: SessionModeRegistry,
        clear_goal: MagicMock,
        recorder: _Recorder,
        tmp_path: Path,
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        result = actor.handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert result.context == []
        assert _labels(modes) == [ModeLabel.GOAL_BLOCKED]
        clear_goal.assert_called_once_with(SESSION)
        notices = modes.take_notices(SESSION)
        assert [n.kind for n in notices] == [NoticeKind.GOAL_LOOP_ENTERED]
        assert notices[0].goal_cleared is True
        (action, evidence), *_ = _registry_actions(modes)
        assert action is TransitionAction.ENTER
        assert "mode=act" in evidence
        assert recorder.actions() == []

    def test_act_block_lasts_blocked_hours(
        self, actor: GoalLoopDetectorHandler, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        actor._blocked_hours = 2
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        actor.handle(_input(transcript))
        (entry,) = modes.active(SESSION)
        assert entry.expires_at - entry.entered_at == pytest.approx(7200.0)

    def test_act_enters_once_not_on_every_further_stop(
        self,
        actor: GoalLoopDetectorHandler,
        modes: SessionModeRegistry,
        clear_goal: MagicMock,
        tmp_path: Path,
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [*_cycle(10), *_cycle(20), *_cycle(30)])
        actor.handle(_input(transcript))
        _append_lines(transcript, _cycle(40))
        actor.handle(_input(transcript))
        assert clear_goal.call_count == 1
        assert len(modes.take_notices(SESSION)) == 1

    def test_observe_logs_would_enter_once_and_not_on_a_fourth_cycle(
        self, handler: GoalLoopDetectorHandler, recorder: _Recorder, tmp_path: Path
    ) -> None:
        def _never() -> SessionModeRegistry:
            raise AssertionError("observe mode must not touch the registry")

        handler._registry = _never
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [*_cycle(10), *_cycle(20), *_cycle(30)])
        handler.handle(_input(transcript))
        _append_lines(transcript, _cycle(40))
        handler.handle(_input(transcript))
        assert recorder.actions() == [TransitionAction.WOULD_ENTER]

    def test_a_repo_change_exits_with_the_cause_logged(
        self, actor: GoalLoopDetectorHandler, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        actor.handle(_input(transcript))
        actor._fingerprint_repo = lambda: "fp-changed"
        _append_lines(transcript, [_stop(500)])
        result = actor.handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert _labels(modes) == []
        assert _registry_actions(modes)[-1] == (
            TransitionAction.EXIT,
            "cause=repo-change fingerprint=fp-stable->fp-changed",
        )
        assert actor._sessions[SESSION].blocked_fingerprint is None

    def test_an_unchanged_repo_keeps_the_block(
        self, actor: GoalLoopDetectorHandler, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        actor.handle(_input(transcript))
        _append_lines(transcript, [_stop(500)])
        actor.handle(_input(transcript))
        assert _labels(modes) == [ModeLabel.GOAL_BLOCKED]
        assert actor._sessions[SESSION].blocked_fingerprint == "fp-stable"

    def test_an_entry_already_ended_by_a_human_drops_the_fingerprint(
        self, actor: GoalLoopDetectorHandler, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        actor.handle(_input(transcript))
        modes.exit(SESSION, ModeLabel.GOAL_BLOCKED, evidence="cause=human-prompt")
        actor._fingerprint_repo = lambda: "fp-changed"
        _append_lines(transcript, [_stop(500)])
        actor.handle(_input(transcript))
        assert actor._sessions[SESSION].blocked_fingerprint is None
        exits = [a for a in _registry_actions(modes) if a[0] is TransitionAction.EXIT]
        assert exits == [(TransitionAction.EXIT, "cause=human-prompt")]

    @pytest.mark.parametrize("error", [OSError("disk full"), RuntimeError("no data layer")])
    def test_an_enter_failure_is_a_named_warning_and_the_stop_is_allowed(
        self,
        actor: GoalLoopDetectorHandler,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        error: Exception,
    ) -> None:
        def _fail() -> SessionModeRegistry:
            raise error

        actor._registry = _fail
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        with caplog.at_level(logging.WARNING):
            result = actor.handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert actor._sessions[SESSION].blocked_fingerprint is None
        assert any(
            "goal-loop detector: goal-blocked mode not entered" in r.getMessage()
            for r in caplog.records
        )

    def test_a_repo_change_exit_failure_is_a_named_warning(
        self,
        actor: GoalLoopDetectorHandler,
        modes: SessionModeRegistry,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        actor.handle(_input(transcript))
        actor._fingerprint_repo = lambda: "fp-changed"
        _append_lines(transcript, [_stop(500)])
        with (
            patch.object(modes, "exit", side_effect=OSError("disk full")),
            caplog.at_level(logging.WARNING),
        ):
            result = actor.handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert any(
            "goal-loop detector: the repo-change exit was not made" in r.getMessage()
            for r in caplog.records
        )

    def test_a_fingerprint_failure_while_blocked_is_a_named_warning(
        self,
        actor: GoalLoopDetectorHandler,
        modes: SessionModeRegistry,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        actor.handle(_input(transcript))

        def _fail() -> str:
            raise FingerprintError("git status failed: boom")

        actor._fingerprint_repo = _fail
        _append_lines(transcript, [_stop(500)])
        with caplog.at_level(logging.WARNING):
            result = actor.handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert _labels(modes) == [ModeLabel.GOAL_BLOCKED]
        assert any("fingerprint failed" in r.getMessage() for r in caplog.records)


class TestProductionSeams:
    def test_default_registry_is_the_data_layers(self, modes: SessionModeRegistry) -> None:
        assert GoalLoopDetectorHandler()._registry() is modes

    def test_default_clear_goal_is_the_ipc_clear_signal(self) -> None:
        with patch(
            "claude_code_hooks_daemon.daemon.session_mode_ipc.clear_goal_signal",
            return_value=False,
        ) as clear:
            assert GoalLoopDetectorHandler()._clear_goal(SESSION) is False
        clear.assert_called_once_with(SESSION)

    def test_default_append_writes_to_the_transition_log(self, tmp_path: Path) -> None:
        log = MagicMock()
        layer = MagicMock()
        layer.session_modes.transition_log = log
        detector = GoalLoopDetectorHandler()
        detector._fingerprint_repo = lambda: "fp"
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        with patch(
            "claude_code_hooks_daemon.handlers.stop.goal_loop_detector.get_data_layer",
            return_value=layer,
        ):
            detector.handle(_input(transcript))
        appended = log.append.call_args.args[0]
        assert [t.action for t in appended] == [TransitionAction.WOULD_ENTER]

    def test_default_append_with_no_transition_log_is_silent(self, tmp_path: Path) -> None:
        layer = MagicMock()
        layer.session_modes.transition_log = None
        detector = GoalLoopDetectorHandler()
        detector._fingerprint_repo = lambda: "fp"
        transcript = tmp_path / "t.jsonl"
        shutil.copy(FIXTURES / "similar_stops.jsonl", transcript)
        with patch(
            "claude_code_hooks_daemon.handlers.stop.goal_loop_detector.get_data_layer",
            return_value=layer,
        ):
            result = detector.handle(_input(transcript))
        assert result.decision == Decision.ALLOW

    def test_default_fingerprint_reads_the_project_root(self, tmp_path: Path) -> None:
        detector = GoalLoopDetectorHandler()
        with (
            patch(
                "claude_code_hooks_daemon.handlers.stop.goal_loop_detector.ProjectContext"
            ) as context,
            patch(
                "claude_code_hooks_daemon.handlers.stop.goal_loop_detector.repo_fingerprint",
                return_value="abc",
            ) as fingerprint,
        ):
            context.project_root.return_value = tmp_path
            assert detector._fingerprint_repo() == "abc"
        fingerprint.assert_called_once_with(tmp_path)


def _typed_clear(second: int, uuid: str = "clear-uuid-1", argument: str = "clear") -> str:
    return json.dumps(
        {
            "type": "system",
            "subtype": "local_command",
            "content": (
                "<command-name>/goal</command-name>\n<command-message>goal</command-message>\n"
                f"<command-args>{argument}</command-args>"
            ),
            "timestamp": _stamp(second),
            "uuid": uuid,
        }
    )


def _epoch(second: int) -> float:
    return datetime.fromisoformat(_stamp(second).replace("Z", "+00:00")).timestamp()


def _write_supervisor_record(directory: Path, *, ts: float) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = record_path(directory, SESSION)
    path.write_text(
        json.dumps({"session_id": SESSION, "ts": ts, "command": "/goal clear"}), encoding="utf-8"
    )
    return path


class TestGoalClearAttribution:
    """Each typed clear is attributed once on the real Stop path (Plan 00501 Task 8.2)."""

    @staticmethod
    def _detector(record_dir: Path) -> GoalLoopDetectorHandler:
        """Production seams except the repository fingerprint and the record directory."""
        detector = GoalLoopDetectorHandler()
        detector._fingerprint_repo = lambda: "fp"
        detector._clear_record_dir = lambda: record_dir
        return detector

    @staticmethod
    def _clears(modes: SessionModeRegistry) -> list[ModeTransition]:
        log = modes.transition_log
        assert log is not None
        return [
            t for t in log.recent(50, session_id=SESSION) if t.action is TransitionAction.GOAL_CLEAR
        ]

    def test_a_clear_the_supervisor_recorded_is_its_and_consumes_the_record(
        self, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        record_dir = tmp_path / "records"
        record = _write_supervisor_record(record_dir, ts=_epoch(10) - 0.5)
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_typed_clear(10)])
        result = self._detector(record_dir).handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        [clear] = self._clears(modes)
        assert clear.detail == "supervisor"
        assert clear.label is ModeLabel.MANUAL_GOALS
        assert not record.exists()
        assert modes.take_lines(SESSION) == ()

    def test_a_clear_with_no_record_is_the_humans(
        self, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_typed_clear(10)])
        self._detector(tmp_path / "records").handle(_input(transcript))
        [clear] = self._clears(modes)
        assert clear.detail == "human"
        assert "record=none" in clear.evidence

    def test_an_unreadable_record_is_assumed_the_supervisors_and_queues_the_line(
        self, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        record_dir = tmp_path / "records"
        record_dir.mkdir()
        record_path(record_dir, SESSION).write_text("{not json", encoding="utf-8")
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_typed_clear(10)])
        self._detector(record_dir).handle(_input(transcript))
        [clear] = self._clears(modes)
        assert clear.detail == "supervisor-assumed"
        [line] = modes.take_lines(SESSION)
        assert "type `/goal clear` again" in line

    def test_a_human_clear_enters_manual_goals_and_states_it_once(
        self, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_typed_clear(10)])
        self._detector(tmp_path / "records").handle(_input(transcript))
        assert modes.policy(SESSION).goal_intent_suppressed is True
        [line] = modes.take_lines(SESSION)
        assert line.startswith("MANUAL GOALS ON:")

    def test_a_second_human_clear_does_not_repeat_the_line(
        self, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        detector = self._detector(tmp_path / "records")
        _append_lines(transcript, [_typed_clear(10, uuid="first")])
        detector.handle(_input(transcript))
        assert len(modes.take_lines(SESSION)) == 1
        _append_lines(transcript, [_typed_clear(20, uuid="second")])
        detector.handle(_input(transcript))
        assert modes.take_lines(SESSION) == ()
        assert modes.policy(SESSION).goal_intent_suppressed is True

    def test_a_supervisor_clear_does_not_enter_manual_goals(
        self, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        record_dir = tmp_path / "records"
        _write_supervisor_record(record_dir, ts=_epoch(10))
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_typed_clear(10)])
        self._detector(record_dir).handle(_input(transcript))
        assert modes.policy(SESSION).goal_intent_suppressed is False

    def test_a_supervisor_assumed_clear_does_not_enter_manual_goals(
        self, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        record_dir = tmp_path / "records"
        record_dir.mkdir()
        record_path(record_dir, SESSION).write_text("{not json", encoding="utf-8")
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_typed_clear(10)])
        self._detector(record_dir).handle(_input(transcript))
        assert modes.policy(SESSION).goal_intent_suppressed is False

    def test_a_typed_goal_condition_changes_nothing(
        self, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_typed_clear(10, argument="ship the parser")])
        self._detector(tmp_path / "records").handle(_input(transcript))
        assert modes.policy(SESSION).goal_intent_suppressed is False
        assert modes.take_lines(SESSION) == ()

    def test_a_failed_entry_is_a_warning_and_the_stop_is_allowed(
        self,
        modes: SessionModeRegistry,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_typed_clear(10)])
        with (
            patch.object(modes, "enter", side_effect=OSError("disk gone")),
            caplog.at_level(logging.WARNING),
        ):
            result = self._detector(tmp_path / "records").handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert "goal-clear attribution" in caplog.text
        assert modes.policy(SESSION).goal_intent_suppressed is False

    def test_a_restart_rereading_the_transcript_does_not_attribute_twice(
        self, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        record_dir = tmp_path / "records"
        _write_supervisor_record(record_dir, ts=_epoch(10))
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_typed_clear(10)])
        self._detector(record_dir).handle(_input(transcript))
        self._detector(record_dir).handle(_input(transcript))
        assert [t.detail for t in self._clears(modes)] == ["supervisor"]

    def test_a_restart_after_the_log_record_is_evicted_does_not_attribute_again(
        self, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        """Plan 00474 review D2: a clear whose log record rotated out stays attributed once.

        The supervisor's record was consumed by the first pass, so a second
        pass would find none and call the clear the human's, turning manual
        goals on uninvited.
        """
        record_dir = tmp_path / "records"
        _write_supervisor_record(record_dir, ts=_epoch(10))
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_typed_clear(10)])
        self._detector(record_dir).handle(_input(transcript))
        restarted = self._detector(record_dir)
        restarted._recent_transitions = lambda _session: []
        restarted.handle(_input(transcript))
        assert [t.detail for t in self._clears(modes)] == ["supervisor"]
        assert modes.policy(SESSION).goal_intent_suppressed is False

    def test_a_failed_mark_leaves_the_clear_unattributed_and_the_stop_allowed(
        self,
        modes: SessionModeRegistry,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        detector = self._detector(tmp_path / "records")
        detector._attributed_clears_path = lambda: tmp_path / "missing-dir" / "x" / "store"
        (tmp_path / "missing-dir").write_text("a file, so the store cannot be made under it")
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_typed_clear(10)])
        with caplog.at_level(logging.WARNING):
            result = detector.handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert self._clears(modes) == []
        assert modes.policy(SESSION).goal_intent_suppressed is False
        assert "goal-clear attribution" in caplog.text

    def test_default_attributed_clears_path_is_in_the_daemon_untracked_dir(
        self, tmp_path: Path
    ) -> None:
        with patch(
            "claude_code_hooks_daemon.handlers.stop.goal_loop_detector.ProjectContext"
        ) as context:
            context.daemon_untracked_dir.return_value = tmp_path
            path = GoalLoopDetectorHandler()._attributed_clears_path()
        assert path == tmp_path / ATTRIBUTED_CLEARS_FILENAME

    def test_a_later_stop_attributes_only_the_new_clear(
        self, modes: SessionModeRegistry, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        detector = self._detector(tmp_path / "records")
        _append_lines(transcript, [_typed_clear(10, uuid="first")])
        detector.handle(_input(transcript))
        _append_lines(transcript, [_typed_clear(20, uuid="second", argument="off")])
        detector.handle(_input(transcript))
        evidence = [t.evidence.split(" ", 1)[0] for t in self._clears(modes)]
        assert evidence == ["clear=first", "clear=second"]

    def test_a_failed_attribution_is_a_warning_and_the_stop_is_allowed(
        self,
        modes: SessionModeRegistry,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        detector = self._detector(tmp_path / "records")

        def _unreachable() -> Path:
            raise OSError("record directory unreachable")

        detector._clear_record_dir = _unreachable
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_typed_clear(10)])
        with caplog.at_level(logging.WARNING):
            result = detector.handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert self._clears(modes) == []
        assert "goal-clear attribution" in caplog.text

    def test_a_clear_with_no_timestamp_is_a_warning_and_the_stop_is_allowed(
        self,
        modes: SessionModeRegistry,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        record = json.loads(_typed_clear(10))
        del record["timestamp"]
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [json.dumps(record)])
        with caplog.at_level(logging.WARNING):
            result = self._detector(tmp_path / "records").handle(_input(transcript))
        assert result.decision == Decision.ALLOW
        assert "goal-clear attribution" in caplog.text

    def test_no_clear_reads_neither_the_log_nor_the_record_directory(self, tmp_path: Path) -> None:
        detector = GoalLoopDetectorHandler()
        detector._fingerprint_repo = lambda: "fp"
        detector._clear_record_dir = MagicMock(side_effect=AssertionError("read"))
        detector._recent_transitions = MagicMock(side_effect=AssertionError("read"))
        detector._attributed_clears_path = MagicMock(side_effect=AssertionError("read"))
        detector._append_transition = _Recorder()
        transcript = tmp_path / "t.jsonl"
        _append_lines(transcript, [_human(1)])
        assert detector.handle(_input(transcript)).decision == Decision.ALLOW

    def test_default_record_dir_is_the_daemon_signal_directory(self, tmp_path: Path) -> None:
        with patch(
            "claude_code_hooks_daemon.handlers.stop.goal_loop_detector.ProjectContext"
        ) as context:
            context.daemon_untracked_dir.return_value = tmp_path
            assert GoalLoopDetectorHandler()._clear_record_dir() == tmp_path / SIGNAL_SUBDIR

    def test_default_recent_transitions_with_no_log_is_empty(self) -> None:
        layer = MagicMock()
        layer.session_modes.transition_log = None
        with patch(
            "claude_code_hooks_daemon.handlers.stop.goal_loop_detector.get_data_layer",
            return_value=layer,
        ):
            assert GoalLoopDetectorHandler()._recent_transitions(SESSION) == []


class TestTransitionActions:
    def test_detector_actions_exist(self) -> None:
        assert TransitionAction("near-miss") is TransitionAction.NEAR_MISS
        assert TransitionAction("would-enter") is TransitionAction.WOULD_ENTER
        assert TransitionAction("loop-reset") is TransitionAction.LOOP_RESET
