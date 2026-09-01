"""Tests for degraded-mode visibility in `status` and `check` (Plan 00304).

A real-repo canary (LongTermSupport/php-qa-ci) found that a daemon degraded
by invalid configuration still reported `status: RUNNING` and a `check`
report byte-identical to a healthy daemon -- only live hook responses
revealed the degraded state. These CLI surfaces must query the daemon's
actual `health` action and surface the SAME degraded signal.
"""

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import cmd_check, cmd_status


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


def _make_project(tmp_path: Path) -> tuple[Path, Path]:
    claude_dir = tmp_path / ".claude"
    hooks_daemon_dir = claude_dir / "hooks-daemon"
    untracked_dir = hooks_daemon_dir / "untracked" / "venv"
    untracked_dir.mkdir(parents=True)
    socket_path = untracked_dir / "socket"
    socket_path.touch()
    config_file = claude_dir / "hooks-daemon.yaml"
    config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")
    return socket_path, untracked_dir


class TestCmdStatusDegradedVisibility:
    def test_reports_degraded_when_daemon_health_says_degraded(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        socket_path, _ = _make_project(tmp_path)
        args = argparse.Namespace(project_root=tmp_path)
        health_response = {
            "result": {
                "status": "degraded",
                "config_errors": ["Removed config option 'monorepo_subproject_patterns'"],
            }
        }

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path", return_value=socket_path),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=health_response,
            ),
        ):
            result = cmd_status(args)

        out = capsys.readouterr().out
        assert result == 0
        assert "DEGRADED" in out
        assert "monorepo_subproject_patterns" in out

    def test_silent_when_daemon_healthy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        socket_path, _ = _make_project(tmp_path)
        args = argparse.Namespace(project_root=tmp_path)
        health_response = {"result": {"status": "healthy", "config_errors": []}}

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path", return_value=socket_path),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=health_response,
            ),
        ):
            result = cmd_status(args)

        out = capsys.readouterr().out
        assert result == 0
        assert "DEGRADED" not in out


class TestCmdCheckDegradedVisibility:
    _OPT_MODULE = (
        "claude_code_hooks_daemon.handlers.session_start.optimal_config_checker."
        "OptimalConfigCheckerHandler._run_checks"
    )
    _FILEMODE_MODULE = (
        "claude_code_hooks_daemon.handlers.session_start.git_filemode_checker."
        "GitFilemodeCheckerHandler._get_filemode_setting"
    )
    _CONTAINER_MODULE = "claude_code_hooks_daemon.utils.container_detection"
    _REGISTRATION = "claude_code_hooks_daemon.daemon.cli.check_hook_registration_warnings"
    _HEALTH = "claude_code_hooks_daemon.daemon.cli._read_project_handler_health"
    _ENFORCEMENT = "claude_code_hooks_daemon.daemon.cli._collect_enforcement_status_lines"

    def _patches(self, *, daemon_health_response: dict[str, Any] | None) -> Any:
        from claude_code_hooks_daemon.daemon.project_handler_health import (
            ProjectHandlerHealthState,
        )

        return (
            patch(self._OPT_MODULE, return_value=[]),
            patch(self._FILEMODE_MODULE, return_value="true"),
            patch(f"{self._CONTAINER_MODULE}.detect_container_runtime", return_value=None),
            patch(f"{self._CONTAINER_MODULE}.in_container", return_value=False),
            patch(self._REGISTRATION, return_value=[]),
            patch(self._HEALTH, return_value=ProjectHandlerHealthState()),
            patch(self._ENFORCEMENT, return_value=[]),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=daemon_health_response,
            ),
        )

    def _enter(self, patches: Any) -> Any:
        from contextlib import ExitStack

        stack = ExitStack()
        for p in patches:
            stack.enter_context(p)
        return stack

    def test_reports_degraded_when_daemon_health_says_degraded(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        health_response = {
            "result": {
                "status": "degraded",
                "config_errors": ["Removed config option 'monorepo_subproject_patterns'"],
            }
        }
        with self._enter(self._patches(daemon_health_response=health_response)):
            cmd_check(argparse.Namespace(project_root=None))

        out = capsys.readouterr().out
        assert "DEGRADED" in out
        assert "monorepo_subproject_patterns" in out

    def test_silent_when_daemon_healthy(self, capsys: pytest.CaptureFixture[str]) -> None:
        health_response = {"result": {"status": "healthy", "config_errors": []}}
        with self._enter(self._patches(daemon_health_response=health_response)):
            cmd_check(argparse.Namespace(project_root=None))

        out = capsys.readouterr().out
        assert "DEGRADED" not in out
