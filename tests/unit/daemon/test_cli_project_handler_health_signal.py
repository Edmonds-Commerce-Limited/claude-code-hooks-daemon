"""CLI degraded-protection signal for project handlers (Plan 00143).

``status`` surfaces a loud degraded line, ``health`` additionally returns a
non-zero exit, and ``check`` includes a project-handler health section — all
driven by the same persisted state the daemon wrote at startup.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_health, cmd_status
from claude_code_hooks_daemon.daemon.project_handler_health import (
    ProjectHandlerHealthState,
)
from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoadFailure

_HEALTH = "claude_code_hooks_daemon.daemon.cli._read_project_handler_health"
_GPP = "claude_code_hooks_daemon.daemon.cli.get_project_path"


def _degraded() -> ProjectHandlerHealthState:
    return ProjectHandlerHealthState(
        failures=[
            ProjectHandlerLoadFailure(
                filename="phpcs_reminder.py",
                event_dir="post_tool_use",
                reason="missing required method get_claude_md (introduced in v2.30.0)",
            )
        ],
        loaded_count=1,
    )


def _healthy() -> ProjectHandlerHealthState:
    return ProjectHandlerHealthState(failures=[], loaded_count=8)


def _running_project(tmp_path: Path) -> tuple[argparse.Namespace, Path]:
    """Build a project dir whose daemon appears RUNNING with a live socket."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "hooks-daemon.yaml").write_text("version: '1.0'\n", encoding="utf-8")
    untracked = claude_dir / "hooks-daemon" / "untracked" / "venv"
    untracked.mkdir(parents=True)
    socket_path = untracked / "socket"
    socket_path.touch()
    return argparse.Namespace(project_root=tmp_path), socket_path


class TestStatusSignal:
    def test_status_warns_when_degraded(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args, socket_path = _running_project(tmp_path)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(_GPP, return_value=tmp_path),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=socket_path,
            ),
            patch(_HEALTH, return_value=_degraded()),
        ):
            cmd_status(args)
        out = capsys.readouterr().out
        assert "DEGRADED" in out
        assert "phpcs_reminder.py" in out

    def test_status_quiet_when_healthy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args, socket_path = _running_project(tmp_path)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(_GPP, return_value=tmp_path),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=socket_path,
            ),
            patch(_HEALTH, return_value=_healthy()),
        ):
            cmd_status(args)
        out = capsys.readouterr().out
        assert "DEGRADED" not in out


class TestHealthSignal:
    def _healthy_response(self) -> dict[str, object]:
        return {
            "result": {
                "status": "healthy",
                "stats": {
                    "uptime_seconds": 1.0,
                    "requests_processed": 1,
                    "avg_processing_time_ms": 1.0,
                    "errors": 0,
                },
                "handlers": {"pre_tool_use": 10},
            }
        }

    def test_health_returns_nonzero_when_degraded(self, tmp_path: Path) -> None:
        args, _ = _running_project(tmp_path)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(_GPP, return_value=tmp_path),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=self._healthy_response(),
            ),
            patch(_HEALTH, return_value=_degraded()),
        ):
            result = cmd_health(args)
        assert result == 1

    def test_health_reports_degraded_detail(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args, _ = _running_project(tmp_path)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(_GPP, return_value=tmp_path),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=self._healthy_response(),
            ),
            patch(_HEALTH, return_value=_degraded()),
        ):
            cmd_health(args)
        out = capsys.readouterr().out
        assert "DEGRADED" in out
        assert "phpcs_reminder.py" in out

    def test_health_returns_zero_when_clean(self, tmp_path: Path) -> None:
        args, _ = _running_project(tmp_path)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(_GPP, return_value=tmp_path),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=self._healthy_response(),
            ),
            patch(_HEALTH, return_value=_healthy()),
        ):
            result = cmd_health(args)
        assert result == 0
