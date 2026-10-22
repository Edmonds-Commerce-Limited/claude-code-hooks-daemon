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
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.goal_loop import FingerprintError, option_problems
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.session_mode_log import ModeTransition, TransitionAction
from claude_code_hooks_daemon.handlers.stop.goal_loop_detector import (
    MAX_TRACKED_SESSIONS,
    GoalLoopDetectorHandler,
)
from claude_code_hooks_daemon.utils.session_modes import ModeLabel

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
        options = {"mode": "act", "cycle_threshold": 0}
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
        # only what is appended after it is.
        _append_lines(transcript, _cycle(50))
        handler.handle(_input(transcript))
        assert recorder.actions()[before:] == [TransitionAction.WOULD_ENTER]
        assert "cycles=4" in recorder.transitions[-1].evidence

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


class TestProductionSeams:
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


class TestTransitionActions:
    def test_detector_actions_exist(self) -> None:
        assert TransitionAction("near-miss") is TransitionAction.NEAR_MISS
        assert TransitionAction("would-enter") is TransitionAction.WOULD_ENTER
        assert TransitionAction("loop-reset") is TransitionAction.LOOP_RESET
