"""The ``hooks-daemon session-mode`` CLI (Plan 00501 Task 3.3).

``session-mode get`` lists the session's modes, ``session-mode focus <task>``
turns focus on and ``session-mode focus off`` (or an alias) turns it off, each
through the session-mode IPC actions. The session defaults to the
``CLAUDE_CODE_SESSION_ID`` a Bash tool call carries; ``--session`` overrides it.
"""

from __future__ import annotations

import argparse
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.modes import SessionModeIPC
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_session_mode

_CLI = "claude_code_hooks_daemon.daemon.cli"


def _args(*argv: str) -> argparse.Namespace:
    return build_parser().parse_args(["session-mode", *argv])


def _run(
    args: argparse.Namespace,
    response: dict[str, Any] | None,
    *,
    pid: int | None = 123,
) -> tuple[int, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def _send(_socket: object, request: dict[str, Any]) -> dict[str, Any] | None:
        sent.append(request)
        return response

    with (
        patch(f"{_CLI}.get_project_path", return_value="/tmp/project"),
        patch(f"{_CLI}._resolve_socket_path", return_value="/tmp/sock"),
        patch(f"{_CLI}._resolve_pid_path", return_value="/tmp/pid"),
        patch(f"{_CLI}.read_pid_file", return_value=pid),
        patch(f"{_CLI}.send_daemon_request", side_effect=_send),
    ):
        code = cmd_session_mode(args)
    return code, sent


@pytest.fixture(autouse=True)
def _session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "env-session")


class TestRequests:
    def test_get_is_the_default(self, capsys: pytest.CaptureFixture[str]) -> None:
        response = {
            "result": {
                SessionModeIPC.KEY_SESSION_ID: "env-session",
                SessionModeIPC.KEY_BADGE: "focus",
                SessionModeIPC.KEY_MODES: [
                    {
                        SessionModeIPC.KEY_LABEL: "focus",
                        SessionModeIPC.KEY_DETAIL: "fix the parser",
                        SessionModeIPC.KEY_EXPIRES_AT: 0.0,
                    }
                ],
            }
        }
        code, sent = _run(_args(), response)
        assert code == 0
        assert sent[0]["hook_input"] == {
            "action": SessionModeIPC.ACTION_GET_SESSION_MODES,
            "session_id": "env-session",
        }
        out = capsys.readouterr().out
        assert "focus" in out
        assert "fix the parser" in out

    def test_get_with_no_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        response = {"result": {SessionModeIPC.KEY_MODES: [], SessionModeIPC.KEY_BADGE: ""}}
        code, _ = _run(_args("get"), response)
        assert code == 0
        assert "no session mode" in capsys.readouterr().out

    def test_get_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        response = {"result": {SessionModeIPC.KEY_MODES: [], SessionModeIPC.KEY_BADGE: ""}}
        code, _ = _run(_args("get", "--json"), response)
        assert code == 0
        assert '"modes": []' in capsys.readouterr().out

    def test_focus_sends_the_joined_task(self, capsys: pytest.CaptureFixture[str]) -> None:
        response = {
            "result": {SessionModeIPC.KEY_OUTCOME: "entered", SessionModeIPC.KEY_LINE: "ON"}
        }
        code, sent = _run(_args("focus", "fix", "the", "parser"), response)
        assert code == 0
        assert sent[0]["hook_input"] == {
            "action": SessionModeIPC.ACTION_ENTER_FOCUS,
            "session_id": "env-session",
            "task": "fix the parser",
        }
        assert "ON" in capsys.readouterr().out

    @pytest.mark.parametrize("alias", ["off", "done", "end", "disable", "OFF"])
    def test_focus_off_and_aliases_exit(self, alias: str) -> None:
        response = {
            "result": {SessionModeIPC.KEY_OUTCOME: "exited", SessionModeIPC.KEY_LINE: "OFF"}
        }
        code, sent = _run(_args("focus", alias), response)
        assert code == 0
        assert sent[0]["hook_input"]["action"] == SessionModeIPC.ACTION_EXIT_FOCUS

    def test_session_flag_overrides_the_environment(self) -> None:
        response = {"result": {SessionModeIPC.KEY_MODES: [], SessionModeIPC.KEY_BADGE: ""}}
        _, sent = _run(_args("get", "--session", "other"), response)
        assert sent[0]["hook_input"]["session_id"] == "other"

    def test_needs_task_exits_non_zero(self) -> None:
        response = {
            "result": {SessionModeIPC.KEY_OUTCOME: "needs-task", SessionModeIPC.KEY_LINE: "x"}
        }
        code, _ = _run(_args("focus", "  "), response)
        assert code == 1


class TestRefusals:
    def test_focus_without_a_task_is_refused_before_the_daemon(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, sent = _run(_args("focus"), None)
        assert code == 1
        assert sent == []
        assert "task" in capsys.readouterr().err

    def test_no_session_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
        code, sent = _run(_args("get"), None)
        assert code == 1
        assert sent == []
        assert "CLAUDE_CODE_SESSION_ID" in capsys.readouterr().err

    def test_daemon_not_running(self) -> None:
        code, sent = _run(_args("get"), None, pid=None)
        assert code == 1
        assert sent == []

    def test_no_response(self) -> None:
        code, _ = _run(_args("get"), None)
        assert code == 1

    def test_an_error_response(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _ = _run(_args("get"), {"error": "disk gone"})
        assert code == 1
        assert "disk gone" in capsys.readouterr().err
