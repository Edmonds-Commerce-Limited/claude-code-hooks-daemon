"""Unit tests for ConfigLoader class.

Following strict TDD methodology - tests written FIRST.
"""

import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from claude_code_hooks_daemon.config.loader import ConfigLoader


class TestConfigLoaderBasicOperations:
    """Test basic config loading operations."""

    def test_load_from_file_yaml(self) -> None:
        """Should load valid YAML configuration file."""
        config_path = "tests/fixtures/valid_config.yaml"
        config = ConfigLoader.load(config_path)

        assert isinstance(config, dict)
        assert config["version"] == "1.0"
        assert "settings" in config
        assert config["settings"]["logging_level"] == "INFO"
        assert "handlers" in config

    def test_load_from_file_json(self) -> None:
        """Should load valid JSON configuration file."""
        config_path = "tests/fixtures/valid_config.json"
        config = ConfigLoader.load(config_path)

        assert isinstance(config, dict)
        assert config["version"] == "1.0"
        assert "settings" in config
        assert config["settings"]["logging_level"] == "DEBUG"

    def test_load_minimal_config(self) -> None:
        """Should load minimal configuration with only version."""
        config_path = "tests/fixtures/minimal_config.yaml"
        config = ConfigLoader.load(config_path)

        assert isinstance(config, dict)
        assert config["version"] == "1.0"
        # Should not error even if no other fields present

    def test_load_nonexistent_file_raises_error(self) -> None:
        """Should raise FileNotFoundError for nonexistent file."""
        with pytest.raises(FileNotFoundError):
            ConfigLoader.load("nonexistent_config.yaml")

    def test_load_invalid_syntax_raises_error(self) -> None:
        """Should raise ValueError for invalid YAML/JSON syntax."""
        config_path = "tests/fixtures/invalid_syntax.yaml"
        with pytest.raises(ValueError, match="Invalid YAML/JSON"):
            ConfigLoader.load(config_path)

    def test_load_unsupported_format_raises_error(self) -> None:
        """Should raise ValueError for unsupported file format."""
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("version: 1.0")
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="Unsupported config format"):
                ConfigLoader.load(temp_path)
        finally:
            Path(temp_path).unlink()

    def test_load_non_dict_content_raises_error(self) -> None:
        """Should raise ValueError if content is not a dictionary."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write("- item1\n- item2\n")
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="Configuration must be a dictionary"):
                ConfigLoader.load(temp_path)
        finally:
            Path(temp_path).unlink()


class TestConfigLoaderDiscovery:
    """Test configuration file discovery."""

    def test_find_config_in_project_dir(self, tmp_path: Path) -> None:
        """Should find config file in .claude directory."""
        # Create .claude directory structure
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'")

        # Should find config
        found_path = ConfigLoader.find_config(str(tmp_path))
        assert found_path == config_file

    def test_find_config_prefers_yaml_over_yml(self, tmp_path: Path) -> None:
        """Should prefer .yaml extension over .yml when both exist."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        yaml_file = claude_dir / "hooks-daemon.yaml"
        yml_file = claude_dir / "hooks-daemon.yml"

        yaml_file.write_text("version: '1.0'")
        yml_file.write_text("version: '2.0'")

        found_path = ConfigLoader.find_config(str(tmp_path))
        assert found_path == yaml_file

    def test_find_config_searches_parent_directories(self, tmp_path: Path) -> None:
        """Should search upward through parent directories."""
        # Create nested directory structure
        nested_dir = tmp_path / "project" / "subdir" / "deep"
        nested_dir.mkdir(parents=True)

        # Place config in project root
        project_root = tmp_path / "project"
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'")

        # Search from deep directory
        found_path = ConfigLoader.find_config(str(nested_dir))
        assert found_path == config_file

    def test_find_config_raises_if_not_found(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError if no config found."""
        with pytest.raises(FileNotFoundError, match=r"No hooks-daemon\.yaml configuration found"):
            ConfigLoader.find_config(str(tmp_path))

    def test_find_config_accepts_yml_extension(self, tmp_path: Path) -> None:
        """Should find .yml extension if .yaml not present."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yml"
        config_file.write_text("version: '1.0'")

        found_path = ConfigLoader.find_config(str(tmp_path))
        assert found_path == config_file


class TestConfigLoaderMerging:
    """Test configuration merging with defaults."""

    def test_merge_with_defaults(self) -> None:
        """Should merge user config with default values."""
        user_config: dict[str, Any] = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True}}},
        }

        merged = ConfigLoader.merge_with_defaults(user_config)

        # Should preserve user values
        assert merged["version"] == "1.0"
        assert merged["handlers"]["pre_tool_use"]["destructive_git"]["enabled"] is True

        # Should add default settings
        assert "settings" in merged
        assert "logging_level" in merged["settings"]
        assert "log_file" in merged["settings"]

    def test_merge_preserves_user_settings(self) -> None:
        """Should not override user-specified settings with defaults."""
        user_config: dict[str, Any] = {
            "version": "1.0",
            "settings": {"logging_level": "DEBUG", "log_file": "/custom/path.log"},
        }

        merged = ConfigLoader.merge_with_defaults(user_config)

        # User settings should be preserved
        assert merged["settings"]["logging_level"] == "DEBUG"
        assert merged["settings"]["log_file"] == "/custom/path.log"

    def test_merge_deep_nested_config(self) -> None:
        """Should deep merge nested configuration structures."""
        user_config: dict[str, Any] = {
            "version": "1.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "git_stash": {"enabled": False},
                }
            },
        }

        merged = ConfigLoader.merge_with_defaults(user_config)

        # Should have deep merged handler configs
        assert merged["handlers"]["pre_tool_use"]["destructive_git"]["enabled"] is True
        assert merged["handlers"]["pre_tool_use"]["destructive_git"]["priority"] == 10
        assert merged["handlers"]["pre_tool_use"]["git_stash"]["enabled"] is False

    def test_merge_with_empty_config(self) -> None:
        """Should handle empty user config by returning all defaults."""
        user_config: dict[str, Any] = {"version": "1.0"}

        merged = ConfigLoader.merge_with_defaults(user_config)

        # Should have all default sections
        assert "version" in merged
        assert "settings" in merged
        assert "handlers" in merged


class TestConfigLoaderHandlerSettings:
    """Test handler-specific settings extraction."""

    def test_get_handler_settings_returns_config(self) -> None:
        """Should extract settings for specific handler."""
        config_path = "tests/fixtures/valid_config.yaml"
        config = ConfigLoader.load(config_path)

        settings = ConfigLoader.get_handler_settings(config, "pre_tool_use", "destructive_git")

        assert settings is not None
        assert settings["enabled"] is True
        assert settings["priority"] == 10

    def test_get_handler_settings_returns_none_if_not_found(self) -> None:
        """Should return None if handler not configured."""
        config_path = "tests/fixtures/minimal_config.yaml"
        config = ConfigLoader.load(config_path)

        settings = ConfigLoader.get_handler_settings(config, "pre_tool_use", "nonexistent")

        assert settings is None

    def test_get_handler_settings_handles_disabled_handler(self) -> None:
        """Should return settings even if handler is disabled."""
        config_path = "tests/fixtures/valid_config.yaml"
        config = ConfigLoader.load(config_path)

        settings = ConfigLoader.get_handler_settings(config, "pre_tool_use", "git_stash")

        assert settings is not None
        assert settings["enabled"] is False
        assert "escape_hatch" in settings

    def test_get_handler_settings_with_default_values(self) -> None:
        """Should provide default values if handler settings incomplete."""
        config: dict[str, Any] = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"simple_handler": {}}},
        }

        settings = ConfigLoader.get_handler_settings(
            config, "pre_tool_use", "simple_handler", defaults={"enabled": True, "priority": 50}
        )

        assert settings is not None
        assert settings["enabled"] is True
        assert settings["priority"] == 50

    def test_get_handler_settings_with_non_dict_handler_config_and_defaults(self) -> None:
        """Should return defaults if handler config is not a dict but defaults provided."""
        config: dict[str, Any] = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"handler_with_boolean": True}},  # Not a dict
        }

        settings = ConfigLoader.get_handler_settings(
            config, "pre_tool_use", "handler_with_boolean", defaults={"enabled": False}
        )

        # Should return defaults when handler_config is not a dict
        assert settings == {"enabled": False}

    def test_get_handler_settings_with_non_dict_handler_config_no_defaults(self) -> None:
        """Should return empty dict if handler config is not a dict and no defaults."""
        config: dict[str, Any] = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"handler_with_string": "enabled"}},  # Not a dict
        }

        settings = ConfigLoader.get_handler_settings(config, "pre_tool_use", "handler_with_string")

        # Should return empty dict when handler_config is not a dict
        assert settings == {}

    def test_get_handler_settings_missing_handlers_section(self) -> None:
        """Should return None if config has no handlers section."""
        config: dict[str, Any] = {"version": "1.0"}

        settings = ConfigLoader.get_handler_settings(config, "pre_tool_use", "any_handler")

        assert settings is None

    def test_get_handler_settings_missing_event_type(self) -> None:
        """Should return None if event type not in handlers."""
        config: dict[str, Any] = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"some_handler": {}}},
        }

        settings = ConfigLoader.get_handler_settings(config, "post_tool_use", "any_handler")

        assert settings is None

    def test_get_handler_settings_handler_not_in_event_type(self) -> None:
        """Should return None when handler_name not in config[handlers][event_type]."""
        config: dict[str, Any] = {
            "version": "1.0",
            "handlers": {
                "pre_tool_use": {
                    "existing_handler": {"enabled": True},
                }
            },
        }

        # Event type exists, but handler_name doesn't exist in that event type
        settings = ConfigLoader.get_handler_settings(config, "pre_tool_use", "nonexistent_handler")

        assert settings is None


class TestConfigLoaderEdgeCases:
    """Test edge cases and error conditions."""

    def test_load_with_extra_fields_succeeds(self) -> None:
        """Should allow extra fields for forward compatibility."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump(
                {
                    "version": "1.0",
                    "future_feature": "some_value",
                    "settings": {"new_setting": 123},
                },
                f,
            )
            temp_path = f.name

        try:
            config = ConfigLoader.load(temp_path)
            # Should load without error
            assert config["version"] == "1.0"
            assert "future_feature" in config
        finally:
            Path(temp_path).unlink()

    def test_load_with_pathlib_path(self) -> None:
        """Should accept pathlib.Path objects."""
        config_path = Path("tests/fixtures/valid_config.yaml")
        config = ConfigLoader.load(config_path)

        assert isinstance(config, dict)
        assert config["version"] == "1.0"

    def test_concurrent_loads_are_safe(self) -> None:
        """Should safely handle concurrent config loading."""
        import concurrent.futures

        config_path = "tests/fixtures/valid_config.yaml"

        def load_config() -> dict[str, Any]:
            return ConfigLoader.load(config_path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(load_config) for _ in range(10)]
            results = [f.result() for f in futures]

        # All loads should succeed with same content
        assert len(results) == 10
        assert all(r["version"] == "1.0" for r in results)
