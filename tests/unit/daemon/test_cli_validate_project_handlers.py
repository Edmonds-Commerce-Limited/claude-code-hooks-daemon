"""Tests for validate-project-handlers CLI command.

Tests validation logic for discovering, importing, and checking project handlers.
"""

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

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


def _create_valid_handler(handlers_dir: Path) -> None:
    """Create a valid project handler for testing."""
    pre_tool_use = handlers_dir / "pre_tool_use"
    pre_tool_use.mkdir(parents=True, exist_ok=True)
    (pre_tool_use / "__init__.py").write_text("")
    (handlers_dir / "__init__.py").write_text("")

    handler_code = '''"""Test handler for validation."""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision


class TestValidHandler(Handler):
    """A valid test handler."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="test-valid-handler",
            priority=50,
            terminal=False,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="Test handler works",
                command="echo test",
                description="Basic test",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                test_type=TestType.ADVISORY,
            ),
        ]
'''
    (pre_tool_use / "valid_handler.py").write_text(handler_code)


class TestValidateProjectHandlers:
    """Tests for cmd_validate_project_handlers command."""

    def test_validates_valid_handler_successfully(self, tmp_path: Path, capsys: Any) -> None:
        """validate-project-handlers reports success for valid handlers."""
        from claude_code_hooks_daemon.daemon.cli import cmd_validate_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        _create_valid_handler(handlers_dir)

        args = argparse.Namespace(project_root=project_path)

        result = cmd_validate_project_handlers(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "test-valid-handler" in captured.out

    def test_reports_no_handlers_found(self, tmp_path: Path, capsys: Any) -> None:
        """validate-project-handlers reports when no handlers found."""
        from claude_code_hooks_daemon.daemon.cli import cmd_validate_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        handlers_dir.mkdir(parents=True)

        args = argparse.Namespace(project_root=project_path)

        result = cmd_validate_project_handlers(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "No project handlers found" in captured.out

    def test_reports_missing_directory(self, tmp_path: Path, capsys: Any) -> None:
        """validate-project-handlers reports when directory doesn't exist."""
        from claude_code_hooks_daemon.daemon.cli import cmd_validate_project_handlers

        project_path = _setup_project(tmp_path)
        args = argparse.Namespace(project_root=project_path)

        result = cmd_validate_project_handlers(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "not found" in captured.out.lower() or "not found" in captured.err.lower()

    def test_detects_handler_without_acceptance_tests(self, tmp_path: Path, capsys: Any) -> None:
        """validate-project-handlers warns about missing acceptance tests."""
        from claude_code_hooks_daemon.daemon.cli import cmd_validate_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        pre_tool_use = handlers_dir / "pre_tool_use"
        pre_tool_use.mkdir(parents=True)
        (handlers_dir / "__init__.py").write_text("")
        (pre_tool_use / "__init__.py").write_text("")

        handler_code = '''"""Handler without acceptance tests."""

from typing import Any
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class NoTestsHandler(Handler):
    def __init__(self) -> None:
        super().__init__(handler_id="no-tests", priority=50, terminal=False)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_acceptance_tests(self) -> list:
        return []
'''
        (pre_tool_use / "no_tests_handler.py").write_text(handler_code)

        args = argparse.Namespace(project_root=project_path)
        result = cmd_validate_project_handlers(args)

        captured = capsys.readouterr()
        assert "no acceptance tests" in captured.out.lower() or "WARNING" in captured.out

    def test_detects_import_error(self, tmp_path: Path, capsys: Any) -> None:
        """validate-project-handlers reports import errors."""
        from claude_code_hooks_daemon.daemon.cli import cmd_validate_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        pre_tool_use = handlers_dir / "pre_tool_use"
        pre_tool_use.mkdir(parents=True)
        (handlers_dir / "__init__.py").write_text("")
        (pre_tool_use / "__init__.py").write_text("")
        (pre_tool_use / "broken_handler.py").write_text("import nonexistent_module_xyz\n")

        args = argparse.Namespace(project_root=project_path)
        result = cmd_validate_project_handlers(args)

        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "broken_handler" in output.lower() or "error" in output.lower()

    def test_returns_1_on_get_project_path_failure(self, tmp_path: Path) -> None:
        """validate-project-handlers returns 1 when project path detection fails."""
        from claude_code_hooks_daemon.daemon.cli import cmd_validate_project_handlers

        args = argparse.Namespace(project_root=tmp_path)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path",
            side_effect=SystemExit(1),
        ):
            result = cmd_validate_project_handlers(args)
            assert result == 1

    def test_counts_handlers_per_event_type(self, tmp_path: Path, capsys: Any) -> None:
        """validate-project-handlers shows handler count per event type."""
        from claude_code_hooks_daemon.daemon.cli import cmd_validate_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        _create_valid_handler(handlers_dir)

        args = argparse.Namespace(project_root=project_path)
        cmd_validate_project_handlers(args)

        captured = capsys.readouterr()
        # Should show the event type where handler was found
        assert "pre_tool_use" in captured.out
