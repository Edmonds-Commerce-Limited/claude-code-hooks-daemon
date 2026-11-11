"""The ``hooks-daemon session-state`` CLI (Plan 00601 Phase 3)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator

from claude_code_hooks_daemon.constants.modes import SessionModeIPC
from claude_code_hooks_daemon.core import state_schemas
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_session_state

_CLI = "claude_code_hooks_daemon.daemon.cli"

_MODE = {
    SessionModeIPC.KEY_LABEL: "focus",
    SessionModeIPC.KEY_MODE: "focus",
    SessionModeIPC.KEY_REASON: None,
    SessionModeIPC.KEY_SOURCE: "human",
    SessionModeIPC.KEY_DETAIL: "x",
    SessionModeIPC.KEY_ENTERED_AT: 1.0,
    SessionModeIPC.KEY_EXPIRES_AT: 2.0,
}


def _args(*argv: str) -> argparse.Namespace:
    return build_parser().parse_args(["session-state", *argv])


def _run(
    args: argparse.Namespace,
    tmp_path: Path,
    response: dict[str, Any] | None,
    *,
    pid: int | None = 123,
) -> tuple[int, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def _send(_socket: object, request: dict[str, Any]) -> dict[str, Any] | None:
        sent.append(request)
        return response

    with (
        patch(f"{_CLI}.get_project_path", return_value=str(tmp_path)),
        patch(f"{_CLI}._daemon_untracked_dir", return_value=tmp_path),
        patch(f"{_CLI}._resolve_socket_path", return_value="/tmp/sock"),
        patch(f"{_CLI}._resolve_pid_path", return_value="/tmp/pid"),
        patch(f"{_CLI}.read_pid_file", return_value=pid),
        patch(f"{_CLI}.send_daemon_request", side_effect=_send),
    ):
        code = cmd_session_state(args)
    return code, sent


def _modes_response() -> dict[str, Any]:
    return {"result": {SessionModeIPC.KEY_SESSION_ID: "s1", SessionModeIPC.KEY_MODES: [_MODE]}}


class TestSessionStateCommand:
    def test_session_is_required(self) -> None:
        with pytest.raises(SystemExit):
            _args("--json")

    def test_json_output_validates_against_the_shipped_schema(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, sent = _run(_args("--json", "--session", "s1"), tmp_path, _modes_response())
        assert code == 0
        assert sent[0]["hook_input"] == {
            "action": SessionModeIPC.ACTION_GET_SESSION_MODES,
            SessionModeIPC.KEY_SESSION_ID: "s1",
        }
        document = json.loads(capsys.readouterr().out)
        Draft202012Validator(
            state_schemas.load_schema(state_schemas.SCHEMA_SESSION_STATE),
            registry=state_schemas.schema_registry(),
        ).validate(document)
        assert document["session_id"] == "s1"
        assert document["modes"] == [_MODE]
        assert document["last_turn_edge"] is None

    def test_json_output_is_one_compact_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(_args("--json", "--session", "s1"), tmp_path, _modes_response())
        assert len(capsys.readouterr().out.strip().splitlines()) == 1

    def test_a_daemon_down_fails_naming_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, sent = _run(_args("--json", "--session", "s1"), tmp_path, None, pid=None)
        assert code == 1
        assert sent == []
        assert "not running" in capsys.readouterr().err

    def test_without_json_prints_a_readable_summary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _sent = _run(_args("--session", "s1"), tmp_path, _modes_response())
        assert code == 0
        assert "s1" in capsys.readouterr().out


class TestPerCallCost:
    """Resolving the project validates the whole config (about 25 ms), so once per call."""

    def test_one_call_resolves_the_project_once(self, tmp_path: Path) -> None:
        with patch(f"{_CLI}.get_project_path", return_value=str(tmp_path)) as resolve:
            _run_with_resolver(_args("--json", "--session", "s1"), tmp_path)
        assert resolve.call_count == 1

    def test_watch_resolves_the_project_once_for_every_poll(self, tmp_path: Path) -> None:
        sleeps: list[float] = []

        def _sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) >= 3:
                raise KeyboardInterrupt

        with (
            patch(f"{_CLI}.time.sleep", side_effect=_sleep),
            patch(f"{_CLI}.get_project_path", return_value=str(tmp_path)) as resolve,
        ):
            _run_with_resolver(_args("--watch", "--session", "s1"), tmp_path)
        assert len(sleeps) == 3
        assert resolve.call_count == 1


def _run_with_resolver(args: argparse.Namespace, tmp_path: Path) -> None:
    """Run the command with only the project resolver left to the caller's patch."""
    with (
        patch(f"{_CLI}._daemon_untracked_dir", return_value=tmp_path),
        patch(f"{_CLI}._resolve_socket_path", return_value="/tmp/sock"),
        patch(f"{_CLI}._resolve_pid_path", return_value="/tmp/pid"),
        patch(f"{_CLI}.read_pid_file", return_value=123),
        patch(f"{_CLI}.send_daemon_request", return_value=_modes_response()),
    ):
        cmd_session_state(args)


class TestWatch:
    def test_watch_streams_one_line_per_change_until_interrupted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sleeps: list[float] = []

        def _sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) >= 2:
                raise KeyboardInterrupt

        with patch(f"{_CLI}.time.sleep", side_effect=_sleep):
            code, _sent = _run(
                _args("--json", "--watch", "--session", "s1", "--interval", "0.5"),
                tmp_path,
                _modes_response(),
            )
        assert code == 0
        assert sleeps == [0.5, 0.5]
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert len(lines) == 1
        Draft202012Validator(
            state_schemas.load_schema(state_schemas.SCHEMA_SESSION_STATE_WATCH),
            registry=state_schemas.schema_registry(),
        ).validate(lines[0])

    def test_a_daemon_failure_mid_watch_ends_it_with_an_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _sent = _run(_args("--json", "--watch", "--session", "s1"), tmp_path, None)
        assert code == 1
        assert "No response" in capsys.readouterr().err

    def test_watch_alone_streams_json_lines(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def _sleep(_seconds: float) -> None:
            raise KeyboardInterrupt

        with patch(f"{_CLI}.time.sleep", side_effect=_sleep):
            code, _sent = _run(_args("--watch", "--session", "s1"), tmp_path, _modes_response())
        assert code == 0
        assert json.loads(capsys.readouterr().out.splitlines()[0])["changed"]
