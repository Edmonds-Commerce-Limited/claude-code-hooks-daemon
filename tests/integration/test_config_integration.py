"""Integration tests for the configuration system.

Tests the full flow the daemon runs at startup: discovery -> loading ->
validation (``ConfigValidator``, the single validation path) -> usage.
Following strict TDD methodology - tests written FIRST.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.validator import ConfigValidator, ValidationError

#: The ``daemon`` section ``ConfigValidator`` requires of every on-disk config.
_DAEMON_SECTION: dict[str, Any] = {"log_level": "INFO", "idle_timeout_seconds": 300}


def _config(**overrides: Any) -> dict[str, Any]:
    """A config the live validator accepts, with ``overrides`` merged on top."""
    base: dict[str, Any] = {
        "version": "1.0",
        "daemon": dict(_DAEMON_SECTION),
        "handlers": {},
    }
    base.update(overrides)
    return base


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    with path.open("w") as f:
        yaml.dump(data, f)


class TestConfigDiscoveryAndLoading:
    """Test complete discovery and loading workflow."""

    def test_discover_load_and_validate_config(self, tmp_path: Path) -> None:
        """Should discover, load, and validate config in one flow."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yaml"
        _write_yaml(
            config_file,
            _config(handlers={"pre_tool_use": {"destructive_git": {"enabled": True}}}),
        )

        found_path = ConfigLoader.find_config(str(tmp_path))
        assert found_path == config_file

        config = ConfigLoader.load(found_path)
        assert config["version"] == "1.0"

        assert ConfigValidator.validate(config) == []

        merged = ConfigLoader.merge_with_defaults(config)
        assert merged["daemon"]["log_level"] == "INFO"
        assert merged["handlers"]["pre_tool_use"]["destructive_git"]["enabled"] is True

    def test_discover_from_subdirectory(self, tmp_path: Path) -> None:
        """Should discover config when running from subdirectory."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        subdir = project_root / "src" / "handlers"
        subdir.mkdir(parents=True)

        claude_dir = project_root / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yaml"
        _write_yaml(config_file, _config())

        found_path = ConfigLoader.find_config(str(subdir))
        assert found_path == config_file

        config = ConfigLoader.load(found_path)
        assert ConfigValidator.validate(config) == []

    def test_fallback_to_defaults_when_no_config_found(self, tmp_path: Path) -> None:
        """Should use defaults when no config file exists."""
        with pytest.raises(FileNotFoundError):
            ConfigLoader.find_config(str(tmp_path))

        minimal_config: dict[str, Any] = {"version": "2.0"}
        merged = ConfigLoader.merge_with_defaults(minimal_config)

        # Finding #29: defaults carry a daemon section
        assert "daemon" in merged
        assert "log_level" in merged["daemon"]

    def test_load_validate_and_extract_handler_settings(self, tmp_path: Path) -> None:
        """Should load config and extract specific handler settings."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yaml"
        _write_yaml(
            config_file,
            _config(
                handlers={
                    "pre_tool_use": {
                        "destructive_git": {"enabled": True, "priority": 10},
                        "git_stash": {
                            "enabled": False,
                            "priority": 20,
                            "escape_hatch": "I CONFIRM",
                        },
                    }
                }
            ),
        )

        config = ConfigLoader.load(config_file)
        assert ConfigValidator.validate(config) == []

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
        """Should fail at validation time for a missing required field."""
        config_file = tmp_path / "no_version.yaml"
        data = _config()
        del data["version"]
        _write_yaml(config_file, data)

        config = ConfigLoader.load(config_file)

        errors = ConfigValidator.validate(config)
        assert "Missing required field: version" in errors
        with pytest.raises(ValidationError):
            ConfigValidator.validate_and_raise(config)

    def test_invalid_enum_value_fails_at_validation(self, tmp_path: Path) -> None:
        """Should fail at validation for invalid enum values."""
        config_file = tmp_path / "bad_enum.yaml"
        _write_yaml(config_file, _config(daemon={**_DAEMON_SECTION, "log_level": "TRACE"}))

        config = ConfigLoader.load(config_file)

        errors = ConfigValidator.validate(config)
        assert any("daemon.log_level" in error and "TRACE" in error for error in errors)

    def test_recoverable_errors_with_defaults(self, tmp_path: Path) -> None:
        """Should recover from incomplete handler config using defaults."""
        config_file = tmp_path / "incomplete.yaml"
        _write_yaml(
            config_file,
            _config(handlers={"pre_tool_use": {"destructive_git": {}}}),
        )

        config = ConfigLoader.load(config_file)
        assert ConfigValidator.validate(config) == []

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
        _write_yaml(config_file, _config(daemon={**_DAEMON_SECTION, "log_level": "DEBUG"}))

        config = ConfigLoader.load(config_file)
        merged = ConfigLoader.merge_with_defaults(config)

        assert merged["daemon"]["log_level"] == "DEBUG"
        assert merged["daemon"]["idle_timeout_seconds"] == 300

    def test_defaults_fill_missing_values(self, tmp_path: Path) -> None:
        """Should add default values for missing sections."""
        config_file = tmp_path / "partial_config.yaml"
        _write_yaml(config_file, {"version": "2.0", "handlers": {}})

        config = ConfigLoader.load(config_file)
        merged = ConfigLoader.merge_with_defaults(config)

        # Finding #29: the default daemon section is added
        assert "daemon" in merged
        assert "log_level" in merged["daemon"]
        assert "idle_timeout_seconds" in merged["daemon"]

    def test_deep_merge_preserves_nested_structure(self, tmp_path: Path) -> None:
        """Should deep merge nested handler configurations."""
        config_file = tmp_path / "nested_config.yaml"
        _write_yaml(
            config_file,
            _config(
                handlers={
                    "pre_tool_use": {
                        "destructive_git": {"enabled": True, "priority": 10},
                        "git_stash": {"enabled": False},
                    }
                }
            ),
        )

        config = ConfigLoader.load(config_file)
        merged = ConfigLoader.merge_with_defaults(config)

        assert merged["handlers"]["pre_tool_use"]["destructive_git"]["enabled"] is True
        assert merged["handlers"]["pre_tool_use"]["destructive_git"]["priority"] == 10
        assert merged["handlers"]["pre_tool_use"]["git_stash"]["enabled"] is False


class TestConfigPluginSystem:
    """Test plugin configuration integration."""

    def test_load_config_with_plugins(self, tmp_path: Path) -> None:
        """Should load and validate config with plugin definitions."""
        config_file = tmp_path / "plugin_config.yaml"
        # Finding #31: plugins is an OBJECT with a 'plugins' list, not a bare array.
        _write_yaml(
            config_file,
            _config(
                version="2.0",
                plugins={
                    "plugins": [
                        {"path": ".claude/hooks/custom", "handlers": ["custom_handler"]},
                        {"path": "/absolute/path/plugins"},
                    ],
                },
            ),
        )

        config = ConfigLoader.load(config_file)
        assert ConfigValidator.validate(config) == []

        assert len(config["plugins"]["plugins"]) == 2
        assert config["plugins"]["plugins"][0]["path"] == ".claude/hooks/custom"

    def test_plugin_without_required_path_fails(self, tmp_path: Path) -> None:
        """Should fail validation if a plugin entry is missing 'path'."""
        config_file = tmp_path / "bad_plugin.yaml"
        _write_yaml(config_file, _config(plugins={"plugins": [{"handlers": ["custom"]}]}))

        config = ConfigLoader.load(config_file)

        errors = ConfigValidator.validate(config)
        assert "Missing required field: plugins.plugins[0].path" in errors

    def test_plugins_as_bare_list_fails(self, tmp_path: Path) -> None:
        """Should reject the pre-Finding-#31 bare-array shape."""
        config_file = tmp_path / "list_plugins.yaml"
        _write_yaml(config_file, _config(plugins=[{"path": "/x"}]))

        config = ConfigLoader.load(config_file)

        errors = ConfigValidator.validate(config)
        assert any("plugins" in error and "dictionary" in error for error in errors)


class TestConfigRealWorldScenarios:
    """Test realistic configuration scenarios."""

    def test_minimal_production_config(self, tmp_path: Path) -> None:
        """Should handle minimal production configuration."""
        config_file = tmp_path / "prod.yaml"
        _write_yaml(
            config_file,
            _config(
                daemon={**_DAEMON_SECTION, "log_level": "WARNING"},
                handlers={"pre_tool_use": {"destructive_git": {"enabled": True}}},
            ),
        )

        config = ConfigLoader.load(config_file)
        assert ConfigValidator.validate(config) == []
        merged = ConfigLoader.merge_with_defaults(config)

        assert merged["daemon"]["log_level"] == "WARNING"
        assert merged["handlers"]["pre_tool_use"]["destructive_git"]["enabled"] is True

    def test_development_config_with_all_options(self, tmp_path: Path) -> None:
        """Should handle comprehensive development configuration."""
        config_file = tmp_path / "dev.yaml"
        _write_yaml(
            config_file,
            _config(
                version="2.0",
                daemon={**_DAEMON_SECTION, "log_level": "DEBUG"},
                handlers={
                    "pre_tool_use": {
                        "destructive_git": {"enabled": True, "priority": 10},
                        "git_stash": {"enabled": False, "priority": 20},
                        "absolute_path": {"enabled": True, "priority": 12},
                    },
                    "session_start": {"docs_qa_sweep": {"enabled": True}},
                },
                # Finding #31: plugins is an OBJECT with a 'plugins' list.
                plugins={
                    "plugins": [
                        {"path": ".claude/hooks/dev_plugins", "handlers": ["debug_handler"]}
                    ],
                },
            ),
        )

        config = ConfigLoader.load(config_file)
        assert ConfigValidator.validate(config) == []
        merged = ConfigLoader.merge_with_defaults(config)

        assert merged["daemon"]["log_level"] == "DEBUG"
        assert len(merged["handlers"]["pre_tool_use"]) >= 3
        assert merged["handlers"]["session_start"]["docs_qa_sweep"]["enabled"] is True
        assert len(merged["plugins"]["plugins"]) == 1

    def test_team_shared_config(self, tmp_path: Path) -> None:
        """Should handle team-shared base configuration."""
        config_file = tmp_path / "team_base.yaml"
        _write_yaml(
            config_file,
            _config(
                handlers={
                    "pre_tool_use": {
                        "destructive_git": {"enabled": True, "priority": 10},
                        "git_stash": {
                            "enabled": True,
                            "priority": 20,
                            "escape_hatch": "TEAM_APPROVED_STASH",
                        },
                    }
                }
            ),
        )

        config = ConfigLoader.load(config_file)
        assert ConfigValidator.validate(config) == []

        stash_settings = ConfigLoader.get_handler_settings(config, "pre_tool_use", "git_stash")
        assert stash_settings is not None
        assert stash_settings["escape_hatch"] == "TEAM_APPROVED_STASH"
