"""Tests for CLI self-install mode support."""

import tempfile
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import _validate_installation


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
            "version: '1.0'\n"
            "daemon:\n"
            "  log_level: INFO\n"
            "  self_install_mode: true\n"
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
            "version: '1.0'\n"
            "daemon:\n"
            "  log_level: INFO\n"
            "  self_install_mode: true\n"
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
            "version: '1.0'\n"
            "daemon:\n"
            "  log_level: INFO\n"
            "  self_install_mode: false\n"
        )

        # Should fail validation (no hooks-daemon directory)
        with pytest.raises(SystemExit):
            _validate_installation(tmp_path)
