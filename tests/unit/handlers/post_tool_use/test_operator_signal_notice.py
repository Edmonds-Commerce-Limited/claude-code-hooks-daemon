"""Unit tests for OperatorSignalNoticeHandler (Plan 00508, GitHub #77).

The ccy supervisor types an operator warning only when the session is idle, so
an agent in a long turn is told late. This handler adds the same warning as
hook context at the next tool boundary, once per signal, and never touches the
signal file the supervisor consumes.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.post_tool_use.operator_signal_notice import (
    OperatorSignalNoticeHandler,
)
from claude_code_hooks_daemon.utils.operator_signal import (
    KIND_REBOOT_CANCELLED,
    KIND_REBOOT_WARNING,
    KIND_SHUTDOWN_WARNING,
    SIGNAL_TTL_SECONDS,
    render_operator_message,
    signal_path,
    write_operator_signal,
)

_SESSION = "notice-sess-1"


@pytest.fixture
def handler() -> OperatorSignalNoticeHandler:
    return OperatorSignalNoticeHandler()


@pytest.fixture
def untracked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "untracked"
    target.mkdir()
    monkeypatch.setattr(ProjectContext, "daemon_untracked_dir", classmethod(lambda cls: target))
    return target


def _event(session_id: str = _SESSION) -> dict[str, Any]:
    return {"hook_event_name": "PostToolUse", "session_id": session_id, "tool_name": "Bash"}


def _signal(
    untracked: Path,
    *,
    session_id: str = _SESSION,
    kind: str = KIND_REBOOT_WARNING,
    minutes: int | None = 10,
    age: float = 5.0,
) -> Path:
    return write_operator_signal(
        untracked,
        session_id=session_id,
        kind=kind,
        minutes=minutes if kind != KIND_REBOOT_CANCELLED else None,
        now=time.time() - age,
    )


class TestRegistration:
    def test_identity_priority_and_non_terminal(self, handler: OperatorSignalNoticeHandler) -> None:
        assert handler.handler_id == HandlerID.OPERATOR_SIGNAL_NOTICE
        assert handler.priority == Priority.OPERATOR_SIGNAL_NOTICE
        assert handler.terminal is False

    def test_ships_enabled(self, handler: OperatorSignalNoticeHandler) -> None:
        assert handler.get_default_enabled() is True

    def test_documents_itself_for_claude_md(self, handler: OperatorSignalNoticeHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "operator_signal_notice" in guidance

    def test_acceptance_tests_expect_allow(self, handler: OperatorSignalNoticeHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert tests
        assert all(t.expected_decision == Decision.ALLOW for t in tests)


class TestMatching:
    def test_event_with_session_matches(self, handler: OperatorSignalNoticeHandler) -> None:
        assert handler.matches(_event()) is True

    @pytest.mark.parametrize("session_id", ["", "   "])
    def test_event_without_session_does_not_match(
        self, handler: OperatorSignalNoticeHandler, session_id: str
    ) -> None:
        assert handler.matches(_event(session_id)) is False

    def test_event_with_no_session_key_does_not_match(
        self, handler: OperatorSignalNoticeHandler
    ) -> None:
        assert handler.matches({"hook_event_name": "PostToolUse"}) is False


class TestSurfacing:
    def test_own_session_signal_is_surfaced_with_text_and_minutes(
        self, handler: OperatorSignalNoticeHandler, untracked: Path
    ) -> None:
        _signal(untracked, kind=KIND_REBOOT_WARNING, minutes=10)
        result = handler.handle(_event())
        assert result.decision == Decision.ALLOW
        assert result.context == [render_operator_message(KIND_REBOOT_WARNING, 10)]
        assert "10 minute(s)" in result.context[0]

    def test_shutdown_warning_is_surfaced(
        self, handler: OperatorSignalNoticeHandler, untracked: Path
    ) -> None:
        _signal(untracked, kind=KIND_SHUTDOWN_WARNING, minutes=3)
        result = handler.handle(_event())
        assert result.context == [render_operator_message(KIND_SHUTDOWN_WARNING, 3)]

    def test_cancelled_notice_is_surfaced(
        self, handler: OperatorSignalNoticeHandler, untracked: Path
    ) -> None:
        _signal(untracked, kind=KIND_REBOOT_CANCELLED)
        result = handler.handle(_event())
        assert result.context == [render_operator_message(KIND_REBOOT_CANCELLED, None)]

    def test_second_event_for_the_same_signal_is_silent(
        self, handler: OperatorSignalNoticeHandler, untracked: Path
    ) -> None:
        _signal(untracked)
        assert handler.handle(_event()).context
        assert not handler.handle(_event()).context

    def test_a_newer_signal_is_surfaced_again(
        self, handler: OperatorSignalNoticeHandler, untracked: Path
    ) -> None:
        _signal(untracked, kind=KIND_REBOOT_WARNING, minutes=10, age=30.0)
        assert handler.handle(_event()).context
        _signal(untracked, kind=KIND_REBOOT_WARNING, minutes=5, age=1.0)
        result = handler.handle(_event())
        assert result.context == [render_operator_message(KIND_REBOOT_WARNING, 5)]

    def test_a_different_kind_is_surfaced_after_the_first(
        self, handler: OperatorSignalNoticeHandler, untracked: Path
    ) -> None:
        _signal(untracked, kind=KIND_REBOOT_WARNING, minutes=10, age=30.0)
        handler.handle(_event())
        _signal(untracked, kind=KIND_REBOOT_CANCELLED, age=1.0)
        assert handler.handle(_event()).context

    def test_signal_is_surfaced_once_per_session(
        self, handler: OperatorSignalNoticeHandler, untracked: Path
    ) -> None:
        _signal(untracked, session_id="sess-a")
        _signal(untracked, session_id="sess-b")
        assert handler.handle(_event("sess-a")).context
        assert handler.handle(_event("sess-b")).context
        assert not handler.handle(_event("sess-a")).context

    def test_no_signal_file_is_silent(
        self, handler: OperatorSignalNoticeHandler, untracked: Path
    ) -> None:
        result = handler.handle(_event())
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_dedupe_memory_is_bounded(
        self, handler: OperatorSignalNoticeHandler, untracked: Path
    ) -> None:
        for index in range(handler.max_remembered * 2):
            session_id = f"sess-{index}"
            _signal(untracked, session_id=session_id)
            assert handler.handle(_event(session_id)).context
        assert handler.remembered_count() <= handler.max_remembered


class TestFileIsNeverTouched:
    def test_signal_file_is_left_in_place_and_unchanged(
        self, handler: OperatorSignalNoticeHandler, untracked: Path
    ) -> None:
        path = _signal(untracked)
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        handler.handle(_event())
        handler.handle(_event())
        assert path.exists()
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before


class TestIgnoredSignals:
    def test_other_sessions_signal_is_not_read(
        self, handler: OperatorSignalNoticeHandler, untracked: Path
    ) -> None:
        _signal(untracked, session_id="someone-else")
        assert not handler.handle(_event()).context

    def test_expired_signal_is_ignored_and_logged(
        self,
        handler: OperatorSignalNoticeHandler,
        untracked: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _signal(untracked, age=SIGNAL_TTL_SECONDS + 60.0)
        with caplog.at_level(logging.DEBUG):
            result = handler.handle(_event())
        assert result.decision == Decision.ALLOW
        assert not result.context
        assert "expired" in caplog.text

    def test_malformed_file_is_ignored_and_logged(
        self,
        handler: OperatorSignalNoticeHandler,
        untracked: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = signal_path(untracked, _SESSION)
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        with caplog.at_level(logging.DEBUG):
            result = handler.handle(_event())
        assert result.decision == Decision.ALLOW
        assert not result.context
        assert "malformed" in caplog.text
        assert path.exists()

    def test_unknown_kind_is_ignored_and_logged(
        self,
        handler: OperatorSignalNoticeHandler,
        untracked: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = signal_path(untracked, _SESSION)
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"ts": time.time(), "session_id": _SESSION, "kind": "evil", "minutes": 5}),
            encoding="utf-8",
        )
        with caplog.at_level(logging.DEBUG):
            result = handler.handle(_event())
        assert not result.context
        assert "unknown kind" in caplog.text

    def test_a_repeated_rejection_is_logged_once(
        self,
        handler: OperatorSignalNoticeHandler,
        untracked: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = signal_path(untracked, _SESSION)
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        with caplog.at_level(logging.DEBUG):
            handler.handle(_event())
            handler.handle(_event())
        assert caplog.text.count("malformed") == 1


class TestNeverRaises:
    def test_missing_project_context_is_silent(
        self, handler: OperatorSignalNoticeHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(cls: type[ProjectContext]) -> Path:
            raise RuntimeError("ProjectContext not initialised")

        monkeypatch.setattr(ProjectContext, "daemon_untracked_dir", classmethod(_raise))
        result = handler.handle(_event())
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_unexpected_reader_failure_is_swallowed(
        self,
        handler: OperatorSignalNoticeHandler,
        untracked: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _boom(*_args: object, **_kwargs: object) -> object:
            raise ValueError("boom")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.post_tool_use.operator_signal_notice."
            "read_signal_notice",
            _boom,
        )
        result = handler.handle(_event())
        assert result.decision == Decision.ALLOW
        assert not result.context
