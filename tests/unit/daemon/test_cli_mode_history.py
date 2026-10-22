"""The ``hooks-daemon mode-history`` CLI (Plan 00501 Task 4.3).

Prints every session's live modes and the newest mode transitions with their
evidence, from the daemon's ``get_mode_history`` IPC action. A daemon error
(an unreadable transition log among them) is printed and exits 1, never shown
as an empty history.
"""

from __future__ import annotations

import argparse
import json
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.modes import SessionModeIPC
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_mode_history

_CLI = "claude_code_hooks_daemon.daemon.cli"

_TRANSITION = {
    "at": 0.0,
    "session_id": "abcdef0123456789",
    "label": "focus",
    "action": "enter",
    "evidence": "a prompt the human typed",
    "detail": "fix the parser",
}

_RESULT = {
    SessionModeIPC.KEY_SESSIONS: {
        "abcdef0123456789": [
            {
                SessionModeIPC.KEY_LABEL: "focus",
                SessionModeIPC.KEY_DETAIL: "fix the parser",
                SessionModeIPC.KEY_EXPIRES_AT: 0.0,
            }
        ]
    },
    SessionModeIPC.KEY_TRANSITIONS: [_TRANSITION],
}


def _args(*argv: str) -> argparse.Namespace:
    return build_parser().parse_args(["mode-history", *argv])


def _run(
    args: argparse.Namespace, response: dict[str, Any] | None, *, pid: int | None = 123
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
        code = cmd_mode_history(args)
    return code, sent


class TestModeHistory:
    def test_default_request_is_every_session_with_the_default_limit(self) -> None:
        code, sent = _run(_args(), {"result": _RESULT})
        assert code == 0
        assert sent == [
            {
                "event": "_system",
                "hook_input": {
                    "action": SessionModeIPC.ACTION_GET_MODE_HISTORY,
                    SessionModeIPC.KEY_LIMIT: SessionModeIPC.DEFAULT_HISTORY_LIMIT,
                },
            }
        ]

    def test_session_and_limit_are_sent(self) -> None:
        _code, sent = _run(_args("--session", "s1", "--limit", "5"), {"result": _RESULT})
        assert sent[0]["hook_input"][SessionModeIPC.KEY_SESSION_ID] == "s1"
        assert sent[0]["hook_input"][SessionModeIPC.KEY_LIMIT] == 5

    def test_prints_active_modes_and_transitions(self, capsys: pytest.CaptureFixture[str]) -> None:
        _run(_args(), {"result": _RESULT})
        out = capsys.readouterr().out
        assert "Active session modes:" in out
        assert "abcdef01" in out
        assert "focus" in out
        assert "Recent transitions" in out
        assert "enter focus (fix the parser) -- a prompt the human typed" in out

    def test_nothing_active_and_no_transitions_says_so(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        empty = {SessionModeIPC.KEY_SESSIONS: {}, SessionModeIPC.KEY_TRANSITIONS: []}
        _run(_args(), {"result": empty})
        out = capsys.readouterr().out
        assert "no session mode is active" in out
        assert "no transitions recorded" in out

    def test_json_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        _run(_args("--json"), {"result": _RESULT})
        assert json.loads(capsys.readouterr().out) == _RESULT

    def test_a_daemon_error_is_printed_and_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _sent = _run(_args(), {"error": "transition log unreadable: line 3"})
        assert code == 1
        assert "transition log unreadable" in capsys.readouterr().err

    def test_a_malformed_transition_is_a_named_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = {SessionModeIPC.KEY_SESSIONS: {}, SessionModeIPC.KEY_TRANSITIONS: [{"at": 1}]}
        code, _sent = _run(_args(), {"result": bad})
        assert code == 1
        assert "malformed transition" in capsys.readouterr().err

    def test_no_daemon_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, sent = _run(_args(), {"result": _RESULT}, pid=None)
        assert code == 1
        assert sent == []
        assert "not running" in capsys.readouterr().err

    def test_no_response_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _sent = _run(_args(), None)
        assert code == 1
        assert "No response" in capsys.readouterr().err

    def test_a_non_positive_limit_is_refused_by_the_parser(self) -> None:
        with pytest.raises(SystemExit):
            _args("--limit", "0")
