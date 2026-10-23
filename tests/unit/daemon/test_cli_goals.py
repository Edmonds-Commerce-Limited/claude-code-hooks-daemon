"""The ``hooks-daemon goals`` CLI (Plan 00501 Task 8.3).

``goals off`` (or ``manual``) puts the session in manual goals and ``goals on``
(or ``auto``) switches automated goals back on, each through the session-mode
IPC actions. The session defaults to the ``CLAUDE_CODE_SESSION_ID`` a Bash tool
call carries; ``--session`` overrides it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.support.autonomy import pin_session_modes

from claude_code_hooks_daemon.constants.modes import SessionModeIPC
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_goals
from claude_code_hooks_daemon.daemon.session_mode_ipc import handle_session_mode_action
from claude_code_hooks_daemon.utils.session_modes import ModeLabel

_CLI = "claude_code_hooks_daemon.daemon.cli"


def _args(*argv: str) -> argparse.Namespace:
    return build_parser().parse_args(["goals", *argv])


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
        code = cmd_goals(args)
    return code, sent


@pytest.fixture(autouse=True)
def _session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "env-session")


def _ok(outcome: str, line: str) -> dict[str, Any]:
    return {"result": {SessionModeIPC.KEY_OUTCOME: outcome, SessionModeIPC.KEY_LINE: line}}


class TestRequests:
    @pytest.mark.parametrize("word", ["off", "manual"])
    def test_off_enters_manual_goals(self, word: str, capsys: pytest.CaptureFixture[str]) -> None:
        code, sent = _run(_args(word), _ok("entered", "MANUAL GOALS ON: x"))
        assert code == 0
        assert sent[0]["hook_input"] == {
            "action": SessionModeIPC.ACTION_ENTER_MANUAL_GOALS,
            SessionModeIPC.KEY_SESSION_ID: "env-session",
        }
        assert "MANUAL GOALS ON" in capsys.readouterr().out

    @pytest.mark.parametrize("word", ["on", "auto"])
    def test_on_exits_manual_goals(self, word: str, capsys: pytest.CaptureFixture[str]) -> None:
        code, sent = _run(_args(word), _ok("exited", "MANUAL GOALS OFF: x"))
        assert code == 0
        assert sent[0]["hook_input"]["action"] == SessionModeIPC.ACTION_EXIT_MANUAL_GOALS
        assert "MANUAL GOALS OFF" in capsys.readouterr().out

    def test_session_flag_overrides_the_environment(self) -> None:
        _, sent = _run(_args("off", "--session", "flag-session"), _ok("entered", "x"))
        assert sent[0]["hook_input"][SessionModeIPC.KEY_SESSION_ID] == "flag-session"

    def test_an_unknown_word_is_rejected_by_the_parser(self) -> None:
        with pytest.raises(SystemExit):
            _args("sideways")


class TestRefusals:
    def test_no_session_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
        code, sent = _run(_args("off"), _ok("entered", "x"))
        assert code == 1
        assert sent == []
        assert "no session" in capsys.readouterr().err

    def test_daemon_not_running(self) -> None:
        code, sent = _run(_args("off"), None, pid=None)
        assert code == 1
        assert sent == []

    def test_an_error_response(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _ = _run(_args("on"), {"error": "session modes unavailable: x"})
        assert code == 1
        assert "session modes unavailable" in capsys.readouterr().err


def test_end_to_end_off_then_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI's requests, answered by the real IPC handler, change the real registry."""
    registry = pin_session_modes(monkeypatch, tmp_path)

    def _answer(_socket: object, request: dict[str, Any]) -> dict[str, Any]:
        hook_input = request["hook_input"]
        return handle_session_mode_action(hook_input["action"], hook_input)

    with (
        patch(f"{_CLI}.get_project_path", return_value="/tmp/project"),
        patch(f"{_CLI}._resolve_socket_path", return_value="/tmp/sock"),
        patch(f"{_CLI}._resolve_pid_path", return_value="/tmp/pid"),
        patch(f"{_CLI}.read_pid_file", return_value=123),
        patch(f"{_CLI}.send_daemon_request", side_effect=_answer),
    ):
        assert cmd_goals(_args("manual")) == 0
        assert [e.label for e in registry.active("env-session")] == [ModeLabel.MANUAL_GOALS]
        assert cmd_goals(_args("auto")) == 0
    assert registry.active("env-session") == ()
    out = capsys.readouterr().out
    assert "MANUAL GOALS ON" in out
    assert "MANUAL GOALS OFF" in out
