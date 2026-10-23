"""The session-mode IPC actions (Plan 00501 Task 3.3).

``get_session_modes``, ``enter_focus`` and ``exit_focus`` reach the same
registry and the same focus operations as the prompt command. The existing
``get_mode``/``set_mode`` actions are untouched. Driven through the real
session-modes registry; the server dispatch is checked on a bare server.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from tests.support.autonomy import awaiting_human_entry, focus_entry, pin_session_modes

from claude_code_hooks_daemon.constants.modes import ModeConstant, SessionModeIPC
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.daemon.server import Controller, HooksDaemon
from claude_code_hooks_daemon.daemon.session_mode_ipc import handle_session_mode_action
from claude_code_hooks_daemon.utils.session_modes import (
    ModeLabel,
    SessionModeEntry,
    goal_loop_blocked_entry,
)

_SESSION = "sess-ipc"
_CLEAR_TARGET = "claude_code_hooks_daemon.daemon.session_mode_ipc.clear_goal_signal"


@pytest.fixture(autouse=True)
def registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SessionModeRegistry:
    return pin_session_modes(monkeypatch, tmp_path)


def _act(action: str, **fields: Any) -> dict[str, Any]:
    with patch(_CLEAR_TARGET, return_value=True) as clear:
        response = handle_session_mode_action(action, {"action": action, **fields})
    response["_clear_calls"] = clear.call_count
    return response


class TestActions:
    def test_the_action_names(self) -> None:
        assert SessionModeIPC.ACTIONS == frozenset(
            {
                "get_session_modes",
                "enter_focus",
                "exit_focus",
                "get_mode_history",
                "exit_blocked",
                "enter_manual_goals",
                "exit_manual_goals",
            }
        )

    def test_focus_changes_record_ipc_evidence(self, tmp_path: Path) -> None:
        _act(SessionModeIPC.ACTION_ENTER_FOCUS, session_id=_SESSION, task="a task")
        _act(SessionModeIPC.ACTION_EXIT_FOCUS, session_id=_SESSION)
        history = _act(SessionModeIPC.ACTION_GET_MODE_HISTORY)["result"]
        evidence = [t["evidence"] for t in history[SessionModeIPC.KEY_TRANSITIONS]]
        assert evidence == [
            "the session-mode CLI or /mode skill",
            "the session-mode CLI or /mode skill",
        ]


class TestModeHistory:
    def test_lists_every_sessions_modes_and_the_transitions(
        self, registry: SessionModeRegistry
    ) -> None:
        registry.enter(focus_entry(_SESSION, "fix the parser"), evidence="typed")
        registry.enter(awaiting_human_entry("other"), evidence="stopped")
        result = _act(SessionModeIPC.ACTION_GET_MODE_HISTORY)["result"]
        sessions = result[SessionModeIPC.KEY_SESSIONS]
        assert sorted(sessions) == ["other", _SESSION]
        assert sessions[_SESSION][0][SessionModeIPC.KEY_LABEL] == "focus"
        assert [t["evidence"] for t in result[SessionModeIPC.KEY_TRANSITIONS]] == [
            "typed",
            "stopped",
        ]

    def test_a_session_and_limit_narrow_the_answer(self, registry: SessionModeRegistry) -> None:
        registry.enter(focus_entry(_SESSION, "one"), evidence="first")
        registry.enter(focus_entry(_SESSION, "two"), evidence="second")
        registry.enter(awaiting_human_entry("other"), evidence="elsewhere")
        result = _act(SessionModeIPC.ACTION_GET_MODE_HISTORY, session_id=_SESSION, limit=1)[
            "result"
        ]
        assert list(result[SessionModeIPC.KEY_SESSIONS]) == [_SESSION]
        assert [t["evidence"] for t in result[SessionModeIPC.KEY_TRANSITIONS]] == ["second"]

    @pytest.mark.parametrize("limit", [0, -1, "5", True])
    def test_a_bad_limit_is_an_error(self, limit: object) -> None:
        assert "limit" in _act(SessionModeIPC.ACTION_GET_MODE_HISTORY, limit=limit)["error"]

    def test_a_blank_session_is_an_error(self) -> None:
        response = _act(SessionModeIPC.ACTION_GET_MODE_HISTORY, session_id=" ")
        assert "session_id" in response["error"]

    def test_an_unreadable_log_is_a_named_error(
        self, registry: SessionModeRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        log = registry.transition_log
        assert log is not None
        log.path.write_text("{broken\n", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            response = _act(SessionModeIPC.ACTION_GET_MODE_HISTORY)
        assert "transition log unreadable" in response["error"]
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_no_transition_log_is_a_named_error(self, registry: SessionModeRegistry) -> None:
        with patch.object(type(registry), "transition_log", None):
            response = _act(SessionModeIPC.ACTION_GET_MODE_HISTORY)
        assert "no transition log" in response["error"]

    def test_get_lists_the_sessions_modes_in_precedence_order(
        self, registry: SessionModeRegistry
    ) -> None:
        registry.enter(focus_entry(_SESSION, "fix the parser"))
        registry.enter(awaiting_human_entry(_SESSION))
        result = _act(SessionModeIPC.ACTION_GET_SESSION_MODES, session_id=_SESSION)["result"]
        assert result[SessionModeIPC.KEY_SESSION_ID] == _SESSION
        assert result[SessionModeIPC.KEY_BADGE] == "awaiting-human +1"
        labels = [mode[SessionModeIPC.KEY_LABEL] for mode in result[SessionModeIPC.KEY_MODES]]
        assert labels == ["awaiting-human", "focus"]
        focus = result[SessionModeIPC.KEY_MODES][1]
        assert focus[SessionModeIPC.KEY_DETAIL] == "fix the parser"
        assert focus[SessionModeIPC.KEY_EXPIRES_AT] > focus[SessionModeIPC.KEY_ENTERED_AT]

    def test_get_with_no_mode_is_empty(self) -> None:
        result = _act(SessionModeIPC.ACTION_GET_SESSION_MODES, session_id=_SESSION)["result"]
        assert result[SessionModeIPC.KEY_MODES] == []
        assert result[SessionModeIPC.KEY_BADGE] == ""

    def test_enter_focus_enters_and_clears_the_goal_once(
        self, registry: SessionModeRegistry
    ) -> None:
        first = _act(SessionModeIPC.ACTION_ENTER_FOCUS, session_id=_SESSION, task="a task")
        second = _act(SessionModeIPC.ACTION_ENTER_FOCUS, session_id=_SESSION, task="b task")
        assert first["result"][SessionModeIPC.KEY_OUTCOME] == "entered"
        assert "FOCUS MODE ON" in first["result"][SessionModeIPC.KEY_LINE]
        assert first["_clear_calls"] == 1
        assert second["result"][SessionModeIPC.KEY_OUTCOME] == "changed"
        assert second["_clear_calls"] == 0
        assert registry.policy(_SESSION).focus_task == "b task"

    def test_enter_focus_without_a_task_is_an_error(self) -> None:
        response = _act(SessionModeIPC.ACTION_ENTER_FOCUS, session_id=_SESSION)
        assert "task" in response["error"]

    def test_enter_focus_with_a_blank_task_needs_a_task(self) -> None:
        response = _act(SessionModeIPC.ACTION_ENTER_FOCUS, session_id=_SESSION, task="  ")
        assert response["result"][SessionModeIPC.KEY_OUTCOME] == "needs-task"

    def test_exit_focus(self, registry: SessionModeRegistry) -> None:
        registry.enter(focus_entry(_SESSION, "fix the parser"))
        result = _act(SessionModeIPC.ACTION_EXIT_FOCUS, session_id=_SESSION)["result"]
        assert result[SessionModeIPC.KEY_OUTCOME] == "exited"
        assert result[SessionModeIPC.KEY_TASK] == "fix the parser"
        assert registry.active(_SESSION) == ()

    @pytest.mark.parametrize("session_id", [None, "", "   ", 7])
    def test_a_missing_session_is_an_error(self, session_id: object) -> None:
        fields = {} if session_id is None else {"session_id": session_id}
        response = _act(SessionModeIPC.ACTION_GET_SESSION_MODES, **fields)
        assert "session_id" in response["error"]

    def test_an_unknown_action_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not a session-mode action"):
            handle_session_mode_action("set_mode", {})

    def test_a_registry_failure_is_an_error_and_a_warning(
        self, registry: SessionModeRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch.object(registry, "enter", side_effect=OSError("disk gone")),
            caplog.at_level(logging.WARNING),
        ):
            response = _act(SessionModeIPC.ACTION_ENTER_FOCUS, session_id=_SESSION, task="x")
        assert "disk gone" in response["error"]
        assert any(r.levelno == logging.WARNING for r in caplog.records)


def _goal_loop_entry(session_id: str) -> SessionModeEntry:
    return goal_loop_blocked_entry(session_id, entered_at=time.time(), ttl_seconds=3600.0)


class TestExitBlocked:
    """``exit_blocked`` ends only a goal-loop entry; a declared entry is refused (Task 6.3)."""

    def test_unblock_ends_goal_blocked_with_explicit_clear_evidence(
        self, registry: SessionModeRegistry
    ) -> None:
        registry.enter(_goal_loop_entry(_SESSION), evidence="cause=goal-loop")
        result = _act(SessionModeIPC.ACTION_EXIT_BLOCKED, session_id=_SESSION)["result"]
        assert result[SessionModeIPC.KEY_OUTCOME] == "unblocked"
        assert result[SessionModeIPC.KEY_LINE]
        assert registry.active(_SESSION) == ()
        log = registry.transition_log
        assert log is not None
        assert log.recent(1)[0].evidence == (
            "cause=explicit-clear (the session-mode CLI or /mode skill)"
        )

    def test_unblock_with_only_a_declared_entry_is_a_named_error_and_the_entry_stays(
        self, registry: SessionModeRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        registry.enter(awaiting_human_entry(_SESSION), evidence="stopped")
        with caplog.at_level(logging.WARNING):
            response = _act(SessionModeIPC.ACTION_EXIT_BLOCKED, session_id=_SESSION)
        assert "result" not in response
        assert "genuine prompt from the human" in response["error"]
        assert [e.label for e in registry.active(_SESSION)] == [ModeLabel.AWAITING_HUMAN]
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_unblock_with_nothing_blocked_is_not_blocked(self) -> None:
        result = _act(SessionModeIPC.ACTION_EXIT_BLOCKED, session_id=_SESSION)["result"]
        assert result[SessionModeIPC.KEY_OUTCOME] == "not-blocked"


class TestManualGoals:
    """``enter_manual_goals``/``exit_manual_goals`` run the prompt command's operations (Task 8.3)."""

    def test_enter_then_exit_records_both_with_ipc_evidence(
        self, registry: SessionModeRegistry
    ) -> None:
        entered = _act(SessionModeIPC.ACTION_ENTER_MANUAL_GOALS, session_id=_SESSION)
        assert entered["result"][SessionModeIPC.KEY_OUTCOME] == "entered"
        assert entered["result"][SessionModeIPC.KEY_LINE].startswith("MANUAL GOALS ON:")
        assert [e.label for e in registry.active(_SESSION)] == [ModeLabel.MANUAL_GOALS]
        exited = _act(SessionModeIPC.ACTION_EXIT_MANUAL_GOALS, session_id=_SESSION)
        assert exited["result"][SessionModeIPC.KEY_OUTCOME] == "exited"
        assert registry.active(_SESSION) == ()
        assert entered["_clear_calls"] == exited["_clear_calls"] == 0
        log = registry.transition_log
        assert log is not None
        evidence = [t.evidence for t in log.recent(2, session_id=_SESSION)]
        assert evidence == ["the session-mode CLI or /mode skill"] * 2

    def test_enter_twice_is_already_manual(self) -> None:
        _act(SessionModeIPC.ACTION_ENTER_MANUAL_GOALS, session_id=_SESSION)
        again = _act(SessionModeIPC.ACTION_ENTER_MANUAL_GOALS, session_id=_SESSION)
        assert again["result"][SessionModeIPC.KEY_OUTCOME] == "already-manual"

    def test_exit_when_not_manual_is_not_manual(self) -> None:
        result = _act(SessionModeIPC.ACTION_EXIT_MANUAL_GOALS, session_id=_SESSION)["result"]
        assert result[SessionModeIPC.KEY_OUTCOME] == "not-manual"

    def test_a_missing_session_is_an_error(self) -> None:
        response = _act(SessionModeIPC.ACTION_ENTER_MANUAL_GOALS)
        assert "result" not in response
        assert "session" in response["error"]


def test_the_goal_clear_writes_the_real_clear_signal(tmp_path: Path) -> None:
    """The deferred-import wrapper reaches goal_injection's writer (the untracked dir is tmp)."""
    from claude_code_hooks_daemon.daemon.session_mode_ipc import clear_goal_signal

    assert clear_goal_signal(_SESSION) is True
    assert list(tmp_path.rglob(f"{_SESSION}.goal-clear"))


class TestServerDispatch:
    def _server(self, controller: Mock | None = None) -> HooksDaemon:
        server = HooksDaemon.__new__(HooksDaemon)
        server.config = Mock()
        server.controller = controller if controller is not None else Mock(spec=Controller)
        server._is_new_controller = True
        return server

    def test_the_server_routes_a_session_mode_action(self, registry: SessionModeRegistry) -> None:
        registry.enter(focus_entry(_SESSION))
        response = self._server()._handle_system_request(
            {"action": SessionModeIPC.ACTION_GET_SESSION_MODES, "session_id": _SESSION}, "r1"
        )
        assert response["request_id"] == "r1"
        assert response["result"][SessionModeIPC.KEY_BADGE] == "focus"

    def test_the_daemon_mode_actions_are_unchanged(self) -> None:
        controller = Mock(spec=Controller)
        controller.get_mode.return_value = {ModeConstant.KEY_MODE: "default"}
        response = self._server(controller)._handle_system_request(
            {"action": ModeConstant.ACTION_GET_MODE}, None
        )
        assert response["result"][ModeConstant.KEY_MODE] == "default"
