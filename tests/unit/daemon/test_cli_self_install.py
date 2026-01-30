"""Tests for CLI self-install mode support."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import _validate_installation


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


class TestSelfInstallMode:
    """Tests for self_install_mode configuration handling in CLI."""

    def test_validate_normal_install_with_directory(self, tmp_path: Path) -> None:
        """Normal install mode requires .claude/hooks-daemon/ directory."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create config without self_install_mode (defaults to False)
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        # Should pass validation
        result = _validate_installation(tmp_path)
        assert result == tmp_path

    def test_validate_normal_install_without_directory_fails(self, tmp_path: Path) -> None:
        """Normal install mode fails without .claude/hooks-daemon/ directory."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        # Create config without self_install_mode
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        # Should fail validation
        with pytest.raises(SystemExit):
            _validate_installation(tmp_path)

    def test_validate_self_install_without_directory_succeeds(self, tmp_path: Path) -> None:
        """Self-install mode succeeds without .claude/hooks-daemon/ directory."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        # Create config with self_install_mode: true
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\n" "daemon:\n" "  log_level: INFO\n" "  self_install_mode: true\n"
        )

        # Should pass validation even without hooks-daemon directory
        result = _validate_installation(tmp_path)
        assert result == tmp_path

    def test_validate_self_install_with_directory_succeeds(self, tmp_path: Path) -> None:
        """Self-install mode also works if hooks-daemon directory exists."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create config with self_install_mode: true
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\n" "daemon:\n" "  log_level: INFO\n" "  self_install_mode: true\n"
        )

        # Should pass validation
        result = _validate_installation(tmp_path)
        assert result == tmp_path

    def test_validate_with_invalid_config_treats_as_normal(self, tmp_path: Path) -> None:
        """Invalid config is treated as normal install mode (safe default)."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        # Create invalid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("invalid: yaml: {{{}}")

        # Should fail validation (no hooks-daemon directory, treated as normal mode)
        with pytest.raises(SystemExit):
            _validate_installation(tmp_path)

    def test_validate_without_config_treats_as_normal(self, tmp_path: Path) -> None:
        """Missing config is treated as normal install mode (safe default)."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        # No config file created

        # Should fail validation (no hooks-daemon directory, treated as normal mode)
        with pytest.raises(SystemExit):
            _validate_installation(tmp_path)

    def test_self_install_mode_false_requires_directory(self, tmp_path: Path) -> None:
        """Explicit self_install_mode: false requires hooks-daemon directory."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        # Create config with explicit self_install_mode: false
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\n" "daemon:\n" "  log_level: INFO\n" "  self_install_mode: false\n"
        )

        # Should fail validation (no hooks-daemon directory)
        with pytest.raises(SystemExit):
            _validate_installation(tmp_path)


class TestNestedInstallationDetection:
    """Tests for nested installation detection in CLI validation."""

    def test_validate_fails_for_nested_installation(self, tmp_path: Path) -> None:
        """Validation fails when nested .claude/hooks-daemon/.claude/hooks-daemon exists."""
        claude_dir = tmp_path / ".claude"
        nested_install = claude_dir / "hooks-daemon" / ".claude" / "hooks-daemon"
        nested_install.mkdir(parents=True)

        # Should fail validation due to nested installation
        with pytest.raises(SystemExit):
            _validate_installation(tmp_path)


class TestHooksDaemonRepoDetection:
    """Tests for hooks-daemon repository detection in CLI validation."""

    def test_validate_fails_for_hooks_daemon_repo_without_self_install(
        self, tmp_path: Path
    ) -> None:
        """Validation fails for hooks-daemon repo without self_install_mode."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (tmp_path / ".git").mkdir()

        # Create config without self_install_mode
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        # Mock is_hooks_daemon_repo to return True
        with patch("claude_code_hooks_daemon.daemon.cli.is_hooks_daemon_repo") as mock_check:
            mock_check.return_value = True

            # Should fail validation
            with pytest.raises(SystemExit):
                _validate_installation(tmp_path)

    def test_validate_succeeds_for_hooks_daemon_repo_with_self_install(
        self, tmp_path: Path
    ) -> None:
        """Validation succeeds for hooks-daemon repo with self_install_mode."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (tmp_path / ".git").mkdir()

        # Create config with self_install_mode
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\ndaemon:\n  log_level: INFO\n  self_install_mode: true\n"
        )

        # Mock is_hooks_daemon_repo to return True
        with patch("claude_code_hooks_daemon.daemon.cli.is_hooks_daemon_repo") as mock_check:
            mock_check.return_value = True

            # Should succeed validation
            result = _validate_installation(tmp_path)
            assert result == tmp_path
