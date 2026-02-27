"""Tests for daemon/init_config.py."""

from unittest.mock import patch

from claude_code_hooks_daemon.daemon.init_config import (
    ConfigTemplate,
    _get_enforcement_line,
    generate_config,
)


class TestGetEnforcementLine:
    """Tests for _get_enforcement_line helper."""

    def test_returns_commented_out_line_when_not_in_container(self) -> None:
        """Returns commented-out enforcement line when not in a container."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            line = _get_enforcement_line()

        assert line.startswith("  #")
        assert "enforce_single_daemon_process" in line

    def test_returns_enabled_line_when_in_container(self) -> None:
        """Returns enabled enforcement line when running in a container."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=True,
        ):
            line = _get_enforcement_line()

        assert "enforce_single_daemon_process: true" in line
        assert not line.startswith("  #")


class TestConfigTemplate:
    """Tests for ConfigTemplate.generate_minimal and generate_full."""

    def test_generate_minimal_returns_yaml_string(self) -> None:
        """generate_minimal returns a valid YAML config string."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            result = ConfigTemplate.generate_minimal()

        assert 'version: "1.0"' in result
        assert "daemon:" in result
        assert "handlers:" in result

    def test_generate_full_returns_yaml_string(self) -> None:
        """generate_full returns a more complete YAML config string."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            result = ConfigTemplate.generate_full()

        assert 'version: "1.0"' in result
        assert "pre_tool_use:" in result
        assert "post_tool_use:" in result

    def test_generate_minimal_in_container_enables_enforcement(self) -> None:
        """generate_minimal includes enabled enforcement line in container."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=True,
        ):
            result = ConfigTemplate.generate_minimal()

        assert "enforce_single_daemon_process: true" in result

    def test_generate_full_in_container_enables_enforcement(self) -> None:
        """generate_full includes enabled enforcement line in container."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=True,
        ):
            result = ConfigTemplate.generate_full()

        assert "enforce_single_daemon_process: true" in result


class TestGenerateConfig:
    """Tests for generate_config convenience function."""

    def test_generate_config_minimal_mode(self) -> None:
        """generate_config with 'minimal' returns minimal template."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            result = generate_config("minimal")

        assert 'version: "1.0"' in result
        # Minimal should not have per-handler entries
        assert "destructive_git" not in result

    def test_generate_config_full_mode(self) -> None:
        """generate_config with 'full' returns full template."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            result = generate_config("full")

        assert "destructive_git" in result

    def test_generate_config_defaults_to_full(self) -> None:
        """generate_config defaults to full mode."""
        with patch(
            "claude_code_hooks_daemon.daemon.init_config.is_container_environment",
            return_value=False,
        ):
            result = generate_config()

        assert "destructive_git" in result
