"""Tests for test-project-handlers CLI command.

Tests the convenience test runner for project handler tests.
"""

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext


@pytest.fixture(autouse=True)
def mock_git_checks(monkeypatch: Any) -> None:
    """Mock git repository checks for tests running in tmp directories."""
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
    """Reset ProjectContext singleton between tests."""
    ProjectContext._initialized = False


def _setup_project(tmp_path: Path) -> Path:
    """Create minimal project structure for CLI tests."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    hooks_daemon_dir = claude_dir / "hooks-daemon"
    hooks_daemon_dir.mkdir()
    config_file = claude_dir / "hooks-daemon.yaml"
    config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")
    return tmp_path


class TestTestProjectHandlers:
    """Tests for cmd_test_project_handlers command."""

    def test_runs_pytest_on_project_handlers(self, tmp_path: Path) -> None:
        """test-project-handlers invokes pytest on project-handlers directory."""
        from claude_code_hooks_daemon.daemon.cli import cmd_test_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        handlers_dir.mkdir()

        args = argparse.Namespace(project_root=project_path, verbose=False)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1 passed\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = cmd_test_project_handlers(args)

            assert result == 0
            mock_run.assert_called_once()

            # Verify pytest is called with correct arguments
            call_args = mock_run.call_args
            cmd_list = call_args[0][0]
            assert "pytest" in str(cmd_list) or "-m" in cmd_list
            assert str(handlers_dir) in str(cmd_list)

    def test_passes_import_mode_importlib(self, tmp_path: Path) -> None:
        """test-project-handlers uses --import-mode=importlib."""
        from claude_code_hooks_daemon.daemon.cli import cmd_test_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        handlers_dir.mkdir()

        args = argparse.Namespace(project_root=project_path, verbose=False)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1 passed\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            cmd_test_project_handlers(args)

            call_args = mock_run.call_args
            cmd_list = call_args[0][0]
            assert "--import-mode=importlib" in cmd_list

    def test_passes_verbose_flag(self, tmp_path: Path) -> None:
        """test-project-handlers passes -v when verbose requested."""
        from claude_code_hooks_daemon.daemon.cli import cmd_test_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        handlers_dir.mkdir()

        args = argparse.Namespace(project_root=project_path, verbose=True)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1 passed\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            cmd_test_project_handlers(args)

            call_args = mock_run.call_args
            cmd_list = call_args[0][0]
            assert "-v" in cmd_list

    def test_returns_pytest_exit_code(self, tmp_path: Path) -> None:
        """test-project-handlers returns pytest exit code on failure."""
        from claude_code_hooks_daemon.daemon.cli import cmd_test_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        handlers_dir.mkdir()

        args = argparse.Namespace(project_root=project_path, verbose=False)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "1 failed\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = cmd_test_project_handlers(args)
            assert result == 1

    def test_reports_missing_directory(self, tmp_path: Path, capsys: Any) -> None:
        """test-project-handlers reports when directory doesn't exist."""
        from claude_code_hooks_daemon.daemon.cli import cmd_test_project_handlers

        project_path = _setup_project(tmp_path)
        args = argparse.Namespace(project_root=project_path, verbose=False)

        result = cmd_test_project_handlers(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "not found" in captured.out.lower()

    def test_returns_1_on_get_project_path_failure(self, tmp_path: Path) -> None:
        """test-project-handlers returns 1 when project path detection fails."""
        from claude_code_hooks_daemon.daemon.cli import cmd_test_project_handlers

        args = argparse.Namespace(project_root=tmp_path, verbose=False)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path",
            side_effect=SystemExit(1),
        ):
            result = cmd_test_project_handlers(args)
            assert result == 1

    def test_handles_subprocess_timeout(self, tmp_path: Path) -> None:
        """test-project-handlers handles subprocess timeout."""
        import subprocess

        from claude_code_hooks_daemon.constants import Timeout
        from claude_code_hooks_daemon.daemon.cli import cmd_test_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        handlers_dir.mkdir()

        args = argparse.Namespace(project_root=project_path, verbose=False)

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=Timeout.QA_TEST_TIMEOUT),
        ):
            result = cmd_test_project_handlers(args)
            assert result == 1

    def test_uses_current_python(self, tmp_path: Path) -> None:
        """test-project-handlers uses sys.executable as the Python interpreter."""
        from claude_code_hooks_daemon.daemon.cli import cmd_test_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        handlers_dir.mkdir()

        args = argparse.Namespace(project_root=project_path, verbose=False)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            cmd_test_project_handlers(args)

            call_args = mock_run.call_args
            cmd_list = call_args[0][0]
            # First element should be the Python executable
            import sys

            assert cmd_list[0] == sys.executable
