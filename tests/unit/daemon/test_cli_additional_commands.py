"""Tests for additional CLI commands (logs, health, handlers, restart).

Covers critical paths in:
- cmd_logs
- cmd_health
- cmd_handlers
- cmd_restart
"""

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import (
    cmd_handlers,
    cmd_health,
    cmd_logs,
    cmd_restart,
)


@pytest.fixture(autouse=True)
def mock_git_checks(monkeypatch: Any) -> None:
    """Mock git repository checks for tests running in tmp directories."""

    def mock_get_git_repo_name(project_root: Path) -> str:
        return "test-repo"

    def mock_get_git_toplevel(project_root: Path) -> Path:
        return project_root

    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_repo_name",
        mock_get_git_repo_name,
    )
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_toplevel",
        mock_get_git_toplevel,
    )


@pytest.fixture(autouse=True)
def reset_project_context() -> None:
    """Reset ProjectContext singleton between tests."""
    ProjectContext._initialized = False


class TestCmdLogs:
    """Tests for cmd_logs command."""

    def test_daemon_not_running(self, tmp_path: Path) -> None:
        """cmd_logs returns 1 when daemon not running."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, count=10, level=None, follow=False)

        with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None):
            result = cmd_logs(args)
            assert result == 1

    def test_successful_logs_query(self, tmp_path: Path) -> None:
        """cmd_logs successfully queries daemon logs."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, count=10, level="INFO", follow=False)

        mock_response = {
            "result": {
                "logs": ["[INFO] Log line 1", "[INFO] Log line 2"],
                "count": 2,
            }
        }

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=mock_response,
            ),
        ):
            result = cmd_logs(args)
            assert result == 0

    def test_logs_no_logs_in_buffer(self, tmp_path: Path) -> None:
        """cmd_logs handles empty log buffer."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, count=10, level=None, follow=False)

        mock_response = {"result": {"logs": [], "count": 0}}

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=mock_response,
            ),
        ):
            result = cmd_logs(args)
            assert result == 0

    def test_logs_daemon_error(self, tmp_path: Path) -> None:
        """cmd_logs handles daemon error response."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, count=10, level=None, follow=False)

        mock_response = {"error": "Internal error"}

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=mock_response,
            ),
        ):
            result = cmd_logs(args)
            assert result == 1

    def test_logs_communication_failure(self, tmp_path: Path) -> None:
        """cmd_logs handles daemon communication failure."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, count=10, level=None, follow=False)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("claude_code_hooks_daemon.daemon.cli.send_daemon_request", return_value=None),
        ):
            result = cmd_logs(args)
            assert result == 1


class TestCmdHealth:
    """Tests for cmd_health command."""

    def test_daemon_not_running(self, tmp_path: Path) -> None:
        """cmd_health returns 1 when daemon not running."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path)

        with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None):
            result = cmd_health(args)
            assert result == 1

    def test_healthy_daemon(self, tmp_path: Path) -> None:
        """cmd_health returns 0 for healthy daemon."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path)

        mock_response = {
            "result": {
                "status": "healthy",
                "stats": {
                    "uptime_seconds": 120.5,
                    "requests_processed": 42,
                    "avg_processing_time_ms": 1.5,
                    "errors": 0,
                },
                "handlers": {
                    "pre_tool_use": 10,
                    "post_tool_use": 3,
                },
            }
        }

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=mock_response,
            ),
        ):
            result = cmd_health(args)
            assert result == 0

    def test_unhealthy_daemon_no_response(self, tmp_path: Path) -> None:
        """cmd_health returns 1 when daemon doesn't respond."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("claude_code_hooks_daemon.daemon.cli.send_daemon_request", return_value=None),
        ):
            result = cmd_health(args)
            assert result == 1

    def test_unhealthy_daemon_error_response(self, tmp_path: Path) -> None:
        """cmd_health returns 1 when daemon returns error."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path)

        mock_response = {"error": "Internal error"}

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=mock_response,
            ),
        ):
            result = cmd_health(args)
            assert result == 1


class TestCmdHandlers:
    """Tests for cmd_handlers command."""

    def test_daemon_not_running(self, tmp_path: Path) -> None:
        """cmd_handlers returns 1 when daemon not running."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, json=False)

        with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None):
            result = cmd_handlers(args)
            assert result == 1

    def test_handlers_text_format(self, tmp_path: Path) -> None:
        """cmd_handlers displays handlers in text format."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, json=False)

        mock_response = {
            "result": {
                "handlers": {
                    "pre_tool_use": [
                        {"name": "handler1", "priority": 10, "terminal": True},
                        {"name": "handler2", "priority": 20, "terminal": False},
                    ],
                    "post_tool_use": [
                        {"name": "handler3", "priority": 30, "terminal": True},
                    ],
                }
            }
        }

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=mock_response,
            ),
        ):
            result = cmd_handlers(args)
            assert result == 0

    def test_handlers_json_format(self, tmp_path: Path) -> None:
        """cmd_handlers displays handlers in JSON format."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, json=True)

        mock_response = {
            "result": {
                "handlers": {
                    "pre_tool_use": [
                        {"name": "handler1", "priority": 10, "terminal": True},
                    ]
                }
            }
        }

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=mock_response,
            ),
        ):
            result = cmd_handlers(args)
            assert result == 0

    def test_handlers_with_empty_list_skipped(self, tmp_path: Path) -> None:
        """cmd_handlers skips event types with empty handler lists."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, json=False)

        mock_response = {
            "result": {
                "handlers": {
                    "pre_tool_use": [
                        {"name": "handler1", "priority": 10, "terminal": True},
                    ],
                    "post_tool_use": [],  # Empty - should be skipped
                    "session_start": [],  # Empty - should be skipped
                }
            }
        }

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=mock_response,
            ),
        ):
            result = cmd_handlers(args)
            assert result == 0

    def test_handlers_communication_failure(self, tmp_path: Path) -> None:
        """cmd_handlers handles daemon communication failure."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, json=False)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("claude_code_hooks_daemon.daemon.cli.send_daemon_request", return_value=None),
        ):
            result = cmd_handlers(args)
            assert result == 1

    def test_handlers_error_response(self, tmp_path: Path) -> None:
        """cmd_handlers handles daemon error response."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, json=False)

        mock_response = {"error": "Internal error"}

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=mock_response,
            ),
        ):
            result = cmd_handlers(args)
            assert result == 1


class TestCmdLogsFollow:
    """Tests for cmd_logs follow mode (lines 448-475)."""

    def test_follow_mode_keyboard_interrupt(self, tmp_path: Path) -> None:
        """Follow mode exits cleanly on KeyboardInterrupt."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, count=10, level=None, follow=True)

        call_count = [0]

        def mock_send(socket_path: object, request: object) -> dict:
            call_count[0] += 1
            if call_count[0] >= 2:
                raise KeyboardInterrupt()
            return {"result": {"logs": ["log1"], "count": 1}}

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                side_effect=mock_send,
            ),
            patch("time.sleep"),
        ):
            result = cmd_logs(args)
            assert result == 0

    def test_follow_mode_communication_failure(self, tmp_path: Path) -> None:
        """Follow mode returns 1 on communication failure."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, count=10, level=None, follow=True)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=None,
            ),
        ):
            result = cmd_logs(args)
            assert result == 1

    def test_follow_mode_error_response(self, tmp_path: Path) -> None:
        """Follow mode returns 1 on error response."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, count=10, level=None, follow=True)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value={"error": "bad"},
            ),
        ):
            result = cmd_logs(args)
            assert result == 1

    def test_follow_mode_prints_new_logs(self, tmp_path: Path) -> None:
        """Follow mode prints only new log entries."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, count=10, level=None, follow=True)

        call_count = [0]

        def mock_send(socket_path: object, request: object) -> dict:
            call_count[0] += 1
            if call_count[0] == 1:
                return {"result": {"logs": ["log1"], "count": 1}}
            if call_count[0] == 2:
                return {"result": {"logs": ["log1", "log2", "log3"], "count": 3}}
            raise KeyboardInterrupt()

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                side_effect=mock_send,
            ),
            patch("time.sleep"),
        ):
            result = cmd_logs(args)
            assert result == 0


class TestCmdRestart:
    """Tests for cmd_restart command."""

    def test_restart_calls_stop_and_start(self, tmp_path: Path) -> None:
        """cmd_restart calls cmd_stop then cmd_start."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.cmd_stop", return_value=0) as mock_stop,
            patch("claude_code_hooks_daemon.daemon.cli.cmd_start", return_value=0) as mock_start,
            patch("time.sleep"),
        ):
            result = cmd_restart(args)
            assert result == 0
            mock_stop.assert_called_once_with(args)
            mock_start.assert_called_once_with(args)
