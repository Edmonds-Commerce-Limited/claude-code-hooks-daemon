"""Integration tests for configuration system.

Tests the full flow: discovery → loading → validation → usage.
Following strict TDD methodology - tests written FIRST.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.schema import ConfigSchema


class TestConfigDiscoveryAndLoading:
    """Test complete discovery and loading workflow."""

    def test_discover_load_and_validate_config(self, tmp_path: Path) -> None:
        """Should discover, load, and validate config in one flow."""
        # Setup: Create config in .claude directory
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yaml"

        config_data = {
            "version": "1.0",
            "settings": {"logging_level": "INFO"},
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True}}},
        }

        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Test: Discover
        found_path = ConfigLoader.find_config(str(tmp_path))
        assert found_path == config_file

        # Test: Load
        config = ConfigLoader.load(found_path)
        assert config["version"] == "1.0"

        # Test: Validate
        ConfigSchema.validate_config(config)  # Should not raise

        # Test: Merge with defaults
        merged = ConfigLoader.merge_with_defaults(config)
        assert "settings" in merged
        assert merged["settings"]["logging_level"] == "INFO"

    def test_discover_from_subdirectory(self, tmp_path: Path) -> None:
        """Should discover config when running from subdirectory."""
        # Create nested structure
        project_root = tmp_path / "project"
        project_root.mkdir()

        subdir = project_root / "src" / "handlers"
        subdir.mkdir(parents=True)

        # Place config in project root
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        # Discover from deep subdirectory
        found_path = ConfigLoader.find_config(str(subdir))
        assert found_path == config_file

        # Load and validate
        config = ConfigLoader.load(found_path)
        ConfigSchema.validate_config(config)

    def test_fallback_to_defaults_when_no_config_found(self, tmp_path: Path) -> None:
        """Should use defaults when no config file exists."""
        # No config file in tmp_path

        # Should raise when searching
        with pytest.raises(FileNotFoundError):
            ConfigLoader.find_config(str(tmp_path))

        # But merging empty config with defaults should work
        minimal_config: dict[str, Any] = {"version": "1.0"}
        merged = ConfigLoader.merge_with_defaults(minimal_config)

        # Should have default values
        assert "settings" in merged
        assert "logging_level" in merged["settings"]

    def test_load_validate_and_extract_handler_settings(self, tmp_path: Path) -> None:
        """Should load config and extract specific handler settings."""
        # Create config with handler settings
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yaml"

        config_data = {
            "version": "1.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "git_stash": {
                        "enabled": False,
                        "priority": 20,
                        "escape_hatch": "I CONFIRM",
                    },
                }
            },
        }

        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Load
        config = ConfigLoader.load(config_file)

        # Validate
        ConfigSchema.validate_config(config)

        # Extract handler settings
        git_settings = ConfigLoader.get_handler_settings(config, "pre_tool_use", "destructive_git")
        assert git_settings is not None
        assert git_settings["enabled"] is True
        assert git_settings["priority"] == 10

        stash_settings = ConfigLoader.get_handler_settings(config, "pre_tool_use", "git_stash")
        assert stash_settings is not None
        assert stash_settings["enabled"] is False
        assert stash_settings["escape_hatch"] == "I CONFIRM"


class TestConfigErrorHandlingIntegration:
    """Test error handling across the configuration system."""

    def test_invalid_syntax_fails_early(self, tmp_path: Path) -> None:
        """Should fail at load time for syntax errors."""
        config_file = tmp_path / "bad_config.yaml"
        config_file.write_text("version: '1.0'\nhandlers:\n  bad\nindent")

        with pytest.raises(ValueError, match="Invalid YAML/JSON"):
            ConfigLoader.load(config_file)

    def test_missing_version_fails_at_validation(self, tmp_path: Path) -> None:
        """Should fail at validation time for schema violations."""
        config_file = tmp_path / "no_version.yaml"
        config_file.write_text("settings:\n  logging_level: INFO\n")

        # Load succeeds (valid YAML)
        config = ConfigLoader.load(config_file)

        # Validation fails (missing version)
        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_invalid_enum_value_fails_at_validation(self, tmp_path: Path) -> None:
        """Should fail at validation for invalid enum values."""
        config_file = tmp_path / "bad_enum.yaml"
        config_data = {"version": "1.0", "settings": {"logging_level": "TRACE"}}

        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = ConfigLoader.load(config_file)

        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_recoverable_errors_with_defaults(self, tmp_path: Path) -> None:
        """Should recover from incomplete config using defaults."""
        config_file = tmp_path / "incomplete.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"destructive_git": {}}},  # Missing enabled/priority
        }

        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = ConfigLoader.load(config_file)
        ConfigSchema.validate_config(config)  # Should pass - extra fields allowed

        # Extract with defaults
        settings = ConfigLoader.get_handler_settings(
            config, "pre_tool_use", "destructive_git", defaults={"enabled": True, "priority": 50}
        )

        assert settings is not None
        assert settings["enabled"] is True
        assert settings["priority"] == 50


class TestConfigMergingIntegration:
    """Test configuration merging with real scenarios."""

    def test_user_overrides_defaults(self, tmp_path: Path) -> None:
        """Should use user values over defaults when merging."""
        config_file = tmp_path / "user_config.yaml"
        config_data = {
            "version": "1.0",
            "settings": {"logging_level": "DEBUG", "log_file": "/custom/path.log"},
        }

        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = ConfigLoader.load(config_file)
        merged = ConfigLoader.merge_with_defaults(config)

        # User values should win
        assert merged["settings"]["logging_level"] == "DEBUG"
        assert merged["settings"]["log_file"] == "/custom/path.log"

    def test_defaults_fill_missing_values(self, tmp_path: Path) -> None:
        """Should add default values for missing settings."""
        config_file = tmp_path / "partial_config.yaml"
        config_data = {"version": "1.0", "handlers": {}}

        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = ConfigLoader.load(config_file)
        merged = ConfigLoader.merge_with_defaults(config)

        # Should have default settings added
        assert "settings" in merged
        assert "logging_level" in merged["settings"]
        assert "log_file" in merged["settings"]

    def test_deep_merge_preserves_nested_structure(self, tmp_path: Path) -> None:
        """Should deep merge nested handler configurations."""
        config_file = tmp_path / "nested_config.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "git_stash": {"enabled": False},
                }
            },
        }

        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = ConfigLoader.load(config_file)
        merged = ConfigLoader.merge_with_defaults(config)

        # Nested structure should be preserved
        assert merged["handlers"]["pre_tool_use"]["destructive_git"]["enabled"] is True
        assert merged["handlers"]["pre_tool_use"]["destructive_git"]["priority"] == 10
        assert merged["handlers"]["pre_tool_use"]["git_stash"]["enabled"] is False


class TestConfigPluginSystem:
    """Test plugin configuration integration."""

    def test_load_config_with_plugins(self, tmp_path: Path) -> None:
        """Should load and validate config with plugin definitions."""
        config_file = tmp_path / "plugin_config.yaml"
        config_data = {
            "version": "1.0",
            "plugins": [
                {"path": ".claude/hooks/custom", "handlers": ["custom_handler"]},
                {"path": "/absolute/path/plugins"},
            ],
        }

        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = ConfigLoader.load(config_file)
        ConfigSchema.validate_config(config)

        assert "plugins" in config
        assert len(config["plugins"]) == 2
        assert config["plugins"][0]["path"] == ".claude/hooks/custom"

    def test_plugin_without_required_path_fails(self, tmp_path: Path) -> None:
        """Should fail validation if plugin missing required 'path'."""
        config_file = tmp_path / "bad_plugin.yaml"
        config_data = {"version": "1.0", "plugins": [{"handlers": ["custom"]}]}

        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = ConfigLoader.load(config_file)

        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)


class TestConfigRealWorldScenarios:
    """Test realistic configuration scenarios."""

    def test_minimal_production_config(self, tmp_path: Path) -> None:
        """Should handle minimal production configuration."""
        config_file = tmp_path / "prod.yaml"
        config_data = {
            "version": "1.0",
            "settings": {"logging_level": "WARNING"},
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True}}},
        }

        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Full workflow
        config = ConfigLoader.load(config_file)
        ConfigSchema.validate_config(config)
        merged = ConfigLoader.merge_with_defaults(config)

        assert merged["settings"]["logging_level"] == "WARNING"
        assert merged["handlers"]["pre_tool_use"]["destructive_git"]["enabled"] is True

    def test_development_config_with_all_options(self, tmp_path: Path) -> None:
        """Should handle comprehensive development configuration."""
        config_file = tmp_path / "dev.yaml"
        config_data = {
            "version": "1.0",
            "settings": {"logging_level": "DEBUG", "log_file": "/var/log/hooks.log"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "git_stash": {"enabled": False, "priority": 20},
                    "absolute_path": {"enabled": True, "priority": 12},
                },
                "session_start": {"enabled": True},
            },
            "plugins": [{"path": ".claude/hooks/dev_plugins", "handlers": ["debug_handler"]}],
        }

        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Full workflow
        config = ConfigLoader.load(config_file)
        ConfigSchema.validate_config(config)
        merged = ConfigLoader.merge_with_defaults(config)

        # Verify all sections loaded correctly
        assert merged["settings"]["logging_level"] == "DEBUG"
        assert len(merged["handlers"]["pre_tool_use"]) >= 3
        assert len(merged["plugins"]) == 1

    def test_team_shared_config(self, tmp_path: Path) -> None:
        """Should handle team-shared base configuration."""
        # Scenario: Team base config with consistent standards
        config_file = tmp_path / "team_base.yaml"
        config_data = {
            "version": "1.0",
            "settings": {"logging_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "git_stash": {
                        "enabled": True,
                        "priority": 20,
                        "escape_hatch": "TEAM_APPROVED_STASH",
                    },
                }
            },
        }

        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        config = ConfigLoader.load(config_file)
        ConfigSchema.validate_config(config)

        # Extract team-standard settings
        stash_settings = ConfigLoader.get_handler_settings(config, "pre_tool_use", "git_stash")
        assert stash_settings is not None
        assert stash_settings["escape_hatch"] == "TEAM_APPROVED_STASH"
