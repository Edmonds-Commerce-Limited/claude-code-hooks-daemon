"""Tests for init-project-handlers CLI command.

Tests scaffolding generation for project-handlers directory structure.
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


class TestInitProjectHandlers:
    """Tests for cmd_init_project_handlers command."""

    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        """init-project-handlers creates the expected directory structure."""
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers

        project_path = _setup_project(tmp_path)
        args = argparse.Namespace(project_root=project_path, force=False)

        result = cmd_init_project_handlers(args)
        assert result == 0

        handlers_dir = project_path / ".claude" / "project-handlers"
        assert handlers_dir.is_dir()
        assert (handlers_dir / "__init__.py").exists()
        assert (handlers_dir / "conftest.py").exists()

    def test_creates_event_type_subdirectories(self, tmp_path: Path) -> None:
        """init-project-handlers creates event type subdirectories."""
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers

        project_path = _setup_project(tmp_path)
        args = argparse.Namespace(project_root=project_path, force=False)

        cmd_init_project_handlers(args)

        handlers_dir = project_path / ".claude" / "project-handlers"
        assert (handlers_dir / "pre_tool_use").is_dir()
        assert (handlers_dir / "pre_tool_use" / "__init__.py").exists()

    def test_creates_example_handler(self, tmp_path: Path) -> None:
        """init-project-handlers creates an example handler with test."""
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers

        project_path = _setup_project(tmp_path)
        args = argparse.Namespace(project_root=project_path, force=False)

        cmd_init_project_handlers(args)

        handlers_dir = project_path / ".claude" / "project-handlers"
        example_handler = handlers_dir / "pre_tool_use" / "example_handler.py"
        example_test = handlers_dir / "pre_tool_use" / "test_example_handler.py"
        assert example_handler.exists()
        assert example_test.exists()

        # Verify handler content has Handler subclass
        handler_content = example_handler.read_text()
        assert "class ExampleHandler(Handler):" in handler_content
        assert "def matches(" in handler_content
        assert "def handle(" in handler_content
        assert "def get_acceptance_tests(" in handler_content

    def test_creates_conftest_with_fixtures(self, tmp_path: Path) -> None:
        """init-project-handlers creates conftest.py with useful fixtures."""
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers

        project_path = _setup_project(tmp_path)
        args = argparse.Namespace(project_root=project_path, force=False)

        cmd_init_project_handlers(args)

        conftest = project_path / ".claude" / "project-handlers" / "conftest.py"
        content = conftest.read_text()
        assert "bash_hook_input" in content
        assert "write_hook_input" in content
        assert "edit_hook_input" in content

    def test_fails_if_directory_exists_without_force(self, tmp_path: Path) -> None:
        """init-project-handlers fails if directory already exists."""
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        handlers_dir.mkdir()

        args = argparse.Namespace(project_root=project_path, force=False)

        result = cmd_init_project_handlers(args)
        assert result == 1

    def test_overwrites_with_force(self, tmp_path: Path) -> None:
        """init-project-handlers overwrites directory with --force."""
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers

        project_path = _setup_project(tmp_path)
        handlers_dir = project_path / ".claude" / "project-handlers"
        handlers_dir.mkdir()

        args = argparse.Namespace(project_root=project_path, force=True)

        result = cmd_init_project_handlers(args)
        assert result == 0
        assert (handlers_dir / "conftest.py").exists()

    def test_updates_config_if_missing_project_handlers_section(self, tmp_path: Path) -> None:
        """init-project-handlers adds project_handlers to config if missing."""
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers

        project_path = _setup_project(tmp_path)
        config_file = project_path / ".claude" / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        args = argparse.Namespace(project_root=project_path, force=False)

        cmd_init_project_handlers(args)

        config_content = config_file.read_text()
        assert "project_handlers" in config_content

    def test_does_not_overwrite_existing_config_section(self, tmp_path: Path) -> None:
        """init-project-handlers preserves existing project_handlers config."""
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers

        project_path = _setup_project(tmp_path)
        config_file = project_path / ".claude" / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\ndaemon:\n  log_level: INFO\n"
            "project_handlers:\n  enabled: true\n  path: custom/path\n"
        )

        args = argparse.Namespace(project_root=project_path, force=False)

        cmd_init_project_handlers(args)

        config_content = config_file.read_text()
        assert "custom/path" in config_content

    def test_returns_1_on_get_project_path_failure(self, tmp_path: Path) -> None:
        """init-project-handlers returns 1 when project path detection fails."""
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers

        args = argparse.Namespace(project_root=tmp_path, force=False)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path",
            side_effect=SystemExit(1),
        ):
            result = cmd_init_project_handlers(args)
            assert result == 1
