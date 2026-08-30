"""Tests for per-event listener visibility in ``cmd_status`` (Plan 00290, Task 2.2)."""

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import cmd_status


@pytest.fixture(autouse=True)
def mock_git_checks(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_repo_name",
        lambda project_root: "test-repo",
    )
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_toplevel",
        lambda project_root: project_root,
    )


@pytest.fixture(autouse=True)
def reset_project_context() -> None:
    ProjectContext._initialized = False


def _make_project(tmp_path: Path, *, transport_yaml: str = "") -> tuple[Path, Path]:
    claude_dir = tmp_path / ".claude"
    hooks_daemon_dir = claude_dir / "hooks-daemon"
    untracked_dir = hooks_daemon_dir / "untracked" / "venv"
    untracked_dir.mkdir(parents=True)
    socket_path = untracked_dir / "socket"
    socket_path.touch()
    config_file = claude_dir / "hooks-daemon.yaml"
    config_file.write_text(f"version: '1.0'\ndaemon:\n  log_level: INFO\n{transport_yaml}")
    return socket_path, untracked_dir


class TestCmdStatusPerEventListeners:
    def test_silent_when_transport_disabled(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        socket_path, _ = _make_project(tmp_path)
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path", return_value=socket_path),
        ):
            result = cmd_status(args)

        assert result == 0
        assert "Per-event listeners" not in capsys.readouterr().out

    def test_reports_active_listeners_when_transport_enabled(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        transport_yaml = "  transport:\n    relay_enabled: true\n"
        socket_path, untracked_dir = _make_project(tmp_path, transport_yaml=transport_yaml)
        events_dir = untracked_dir / "events-whatever-suffix"
        events_dir.mkdir()
        (events_dir / "pre-tool-use.sock").touch()
        (events_dir / "stop.sock").touch()

        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path", return_value=socket_path),
            patch(
                "claude_code_hooks_daemon.daemon.paths.get_event_socket_dir",
                return_value=events_dir,
            ),
        ):
            result = cmd_status(args)

        out = capsys.readouterr().out
        assert result == 0
        assert "Per-event listeners: 2 active" in out

    def test_reports_missing_events_dir_when_transport_enabled_but_unbound(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        transport_yaml = "  transport:\n    nc_enabled: true\n"
        socket_path, untracked_dir = _make_project(tmp_path, transport_yaml=transport_yaml)
        missing_events_dir = untracked_dir / "events-nonexistent"

        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path", return_value=socket_path),
            patch(
                "claude_code_hooks_daemon.daemon.paths.get_event_socket_dir",
                return_value=missing_events_dir,
            ),
        ):
            result = cmd_status(args)

        out = capsys.readouterr().out
        assert result == 0
        assert "Per-event listeners: transport enabled but events dir not found" in out
