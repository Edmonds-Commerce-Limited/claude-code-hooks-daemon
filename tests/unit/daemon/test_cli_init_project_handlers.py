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

        # Verify the handler subclasses its EVENT's base, not plain `Handler`.
        # The scaffold lands in pre_tool_use/, so the gating tier is the correct
        # one. This matters because the scaffold is what every client project
        # starts from: emitting plain `Handler` while PROJECT_HANDLERS.md tells
        # people to use the event base put the tool and the docs in conflict.
        handler_content = example_handler.read_text()
        assert "class ExampleHandler(PreToolUseHandlerBase):" in handler_content
        assert "PreToolUseHandlerBase" in handler_content
        assert "-> GatingResult:" in handler_content
        assert "def matches(" in handler_content
        assert "def handle(" in handler_content
        assert "def get_acceptance_tests(" in handler_content

    def test_scaffolded_handler_implements_every_required_abstract_method(
        self, tmp_path: Path
    ) -> None:
        """The scaffold must satisfy the validator that ships alongside it.

        Regression test: init-project-handlers emitted an ExampleHandler with no
        get_claude_md(), so validate-project-handlers rejected the daemon's OWN
        scaffold and project_handler_load_checker raised "PROJECT PROTECTION
        DEGRADED" on the client's next session.

        Asserted against _ABSTRACT_METHOD_VERSIONS rather than a hardcoded name,
        so adding a future required method fails here instead of silently
        shipping a broken scaffold again.
        """
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers
        from claude_code_hooks_daemon.handlers.project_loader import (
            _ABSTRACT_METHOD_VERSIONS,
        )

        project_path = _setup_project(tmp_path)
        args = argparse.Namespace(project_root=project_path, force=False)

        cmd_init_project_handlers(args)

        handler_content = (
            project_path / ".claude" / "project-handlers" / "pre_tool_use" / "example_handler.py"
        ).read_text()

        missing = [
            method_name
            for method_name in _ABSTRACT_METHOD_VERSIONS
            if f"def {method_name}(" not in handler_content
        ]
        assert not missing, (
            f"Scaffolded example handler is missing required abstract method(s): "
            f"{missing}. validate-project-handlers will reject the daemon's own "
            f"scaffold."
        )

    def test_scaffolded_handler_loads_through_the_real_validator(self, tmp_path: Path) -> None:
        """The scaffold must load cleanly through ProjectHandlerLoader itself.

        Stronger than a text scan: runs the production loader over the emitted
        tree and asserts zero failures. ABCMeta refuses to instantiate a class
        with unimplemented abstract methods, so this reproduces the exact defect
        validate-project-handlers reported against the daemon's own scaffold.
        """
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers
        from claude_code_hooks_daemon.handlers.project_loader import (
            ProjectHandlerLoader,
        )

        project_path = _setup_project(tmp_path)
        args = argparse.Namespace(project_root=project_path, force=False)

        cmd_init_project_handlers(args)

        result = ProjectHandlerLoader.discover_handlers_with_failures(
            project_path / ".claude" / "project-handlers"
        )

        assert not result.failures, (
            "ProjectHandlerLoader rejected the daemon's own scaffold: "
            f"{[f.reason for f in result.failures]}"
        )
        assert result.handlers, "Scaffold produced no loadable handlers"

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

    def test_conftest_uses_snake_case_keys(self, tmp_path: Path) -> None:
        """Conftest fixtures must use snake_case keys matching daemon protocol."""
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers

        project_path = _setup_project(tmp_path)
        args = argparse.Namespace(project_root=project_path, force=False)

        cmd_init_project_handlers(args)

        conftest = project_path / ".claude" / "project-handlers" / "conftest.py"
        content = conftest.read_text()

        # Must use snake_case (daemon protocol)
        assert '"tool_name"' in content, "conftest must use snake_case 'tool_name'"
        assert '"tool_input"' in content, "conftest must use snake_case 'tool_input'"

        # Must NOT use camelCase
        assert '"toolName"' not in content, "conftest must not use camelCase 'toolName'"
        assert '"toolInput"' not in content, "conftest must not use camelCase 'toolInput'"

    def test_example_handler_uses_snake_case_keys(self, tmp_path: Path) -> None:
        """Example handler must use snake_case keys matching daemon protocol."""
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers

        project_path = _setup_project(tmp_path)
        args = argparse.Namespace(project_root=project_path, force=False)

        cmd_init_project_handlers(args)

        handler = (
            project_path / ".claude" / "project-handlers" / "pre_tool_use" / "example_handler.py"
        )
        content = handler.read_text()

        # Must use snake_case (daemon protocol)
        assert '"tool_input"' in content, "example handler must use snake_case 'tool_input'"

        # Must NOT use camelCase
        assert '"toolInput"' not in content, "example handler must not use camelCase 'toolInput'"

    def test_conftest_includes_sys_path_setup(self, tmp_path: Path) -> None:
        """Conftest must add event-type subdirectories to sys.path for co-located test imports."""
        from claude_code_hooks_daemon.daemon.cli import cmd_init_project_handlers

        project_path = _setup_project(tmp_path)
        args = argparse.Namespace(project_root=project_path, force=False)

        cmd_init_project_handlers(args)

        conftest = project_path / ".claude" / "project-handlers" / "conftest.py"
        content = conftest.read_text()

        assert "sys.path" in content, "conftest must set up sys.path for co-located test imports"
        assert "import sys" in content, "conftest must import sys"

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
