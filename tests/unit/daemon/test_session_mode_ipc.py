"""The session-mode IPC actions (Plan 00501 Task 3.3).

``get_session_modes``, ``enter_focus`` and ``exit_focus`` reach the same
registry and the same focus operations as the prompt command. The existing
``get_mode``/``set_mode`` actions are untouched. Driven through the real
session-modes registry; the server dispatch is checked on a bare server.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from tests.support.autonomy import awaiting_human_entry, focus_entry, pin_session_modes

from claude_code_hooks_daemon.constants.modes import ModeConstant, SessionModeIPC
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.daemon.server import Controller, HooksDaemon
from claude_code_hooks_daemon.daemon.session_mode_ipc import handle_session_mode_action

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
            {"get_session_modes", "enter_focus", "exit_focus"}
        )

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
        response = self._server(controller)._handle_system_request({"action": ModeConstant.ACTION_GET_MODE}, None)
        assert response["result"][ModeConstant.KEY_MODE] == "default"
