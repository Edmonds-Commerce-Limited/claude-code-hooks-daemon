"""Unit tests for ConfigSchema validation.

Following strict TDD methodology - tests written FIRST.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.schema import ConfigSchema


class TestConfigSchemaValidation:
    """Test configuration schema validation."""

    def test_valid_config_passes_validation(self) -> None:
        """Should validate a correct configuration."""
        config: dict[str, Any] = {
            "version": "1.0",
            "settings": {"logging_level": "INFO", "log_file": ".claude/hooks/daemon.log"},
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True}}},
        }

        # Should not raise
        ConfigSchema.validate_config(config)

    def test_minimal_config_passes_validation(self) -> None:
        """Should validate minimal config with just version."""
        config: dict[str, Any] = {"version": "1.0"}

        # Should not raise
        ConfigSchema.validate_config(config)

    def test_missing_version_fails_validation(self) -> None:
        """Should fail validation if version missing."""
        config: dict[str, Any] = {
            "settings": {"logging_level": "INFO"},
            "handlers": {},
        }

        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_invalid_version_format_fails_validation(self) -> None:
        """Should fail if version not in 'major.minor' format."""
        config: dict[str, Any] = {"version": "1.0.0"}  # Should be "1.0"

        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_invalid_logging_level_fails_validation(self) -> None:
        """Should fail if logging level not in allowed enum."""
        config: dict[str, Any] = {
            "version": "1.0",
            "settings": {"logging_level": "TRACE"},  # Not valid
        }

        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_valid_logging_levels_pass_validation(self) -> None:
        """Should accept all valid logging levels."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

        for level in valid_levels:
            config: dict[str, Any] = {
                "version": "1.0",
                "settings": {"logging_level": level},
            }
            # Should not raise
            ConfigSchema.validate_config(config)

    def test_invalid_handler_priority_type_fails_validation(self) -> None:
        """Should fail if priority is not an integer."""
        config: dict[str, Any] = {
            "version": "1.0",
            "handlers": {
                "pre_tool_use": {"destructive_git": {"enabled": True, "priority": "high"}}
            },
        }

        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_extra_fields_allowed(self) -> None:
        """Should allow extra fields for forward compatibility."""
        config: dict[str, Any] = {
            "version": "1.0",
            "future_setting": "some_value",
            "settings": {"new_option": True, "logging_level": "INFO"},
        }

        # Should not raise - forward compatibility
        ConfigSchema.validate_config(config)

    def test_handlers_must_be_object(self) -> None:
        """Should fail if handlers is not an object."""
        config: dict[str, Any] = {"version": "1.0", "handlers": "invalid"}

        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_settings_must_be_object(self) -> None:
        """Should fail if settings is not an object."""
        config: dict[str, Any] = {"version": "1.0", "settings": ["invalid"]}

        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_plugins_must_be_array(self) -> None:
        """Should fail if plugins is not an array."""
        config: dict[str, Any] = {"version": "1.0", "plugins": "invalid"}

        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_plugin_must_have_path(self) -> None:
        """Should fail if plugin entry missing required 'path' field."""
        config: dict[str, Any] = {
            "version": "1.0",
            "plugins": [{"handlers": ["custom"]}],  # Missing 'path'
        }

        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_valid_plugin_config_passes(self) -> None:
        """Should validate correct plugin configuration."""
        config: dict[str, Any] = {
            "version": "1.0",
            "plugins": [
                {"path": ".claude/hooks/custom", "handlers": ["handler1", "handler2"]},
                {"path": "/absolute/path/plugins"},
            ],
        }

        # Should not raise
        ConfigSchema.validate_config(config)


class TestConfigSchemaIntegration:
    """Test schema validation integration with config loading."""

    def test_load_and_validate_valid_config(self) -> None:
        """Should load and validate valid config file."""
        config_path = "tests/fixtures/valid_config.yaml"
        config = ConfigLoader.load(config_path)

        # Should validate without error
        ConfigSchema.validate_config(config)

    def test_load_and_validate_minimal_config(self) -> None:
        """Should load and validate minimal config file."""
        config_path = "tests/fixtures/minimal_config.yaml"
        config = ConfigLoader.load(config_path)

        # Should validate without error
        ConfigSchema.validate_config(config)

    def test_load_invalid_config_then_validate_fails(self) -> None:
        """Should fail validation on invalid config."""
        config_path = "tests/fixtures/invalid_config.yaml"
        config = ConfigLoader.load(config_path)

        # Should fail validation (missing version)
        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_load_invalid_version_format_then_validate_fails(self) -> None:
        """Should fail validation on incorrect version format."""
        config_path = "tests/fixtures/invalid_version_format.yaml"
        config = ConfigLoader.load(config_path)

        # Should fail validation (version format wrong)
        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_load_invalid_logging_level_then_validate_fails(self) -> None:
        """Should fail validation on invalid logging level."""
        config_path = "tests/fixtures/invalid_logging_level.yaml"
        config = ConfigLoader.load(config_path)

        # Should fail validation (invalid enum value)
        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)


class TestConfigSchemaGetSchema:
    """Test schema retrieval and structure."""

    def test_get_config_schema_returns_dict(self) -> None:
        """Should return schema as dictionary."""
        schema = ConfigSchema.get_config_schema()

        assert isinstance(schema, dict)
        assert "type" in schema
        assert schema["type"] == "object"

    def test_schema_has_required_fields(self) -> None:
        """Should define required fields in schema."""
        schema = ConfigSchema.get_config_schema()

        assert "required" in schema
        assert "version" in schema["required"]

    def test_schema_defines_properties(self) -> None:
        """Should define property specifications."""
        schema = ConfigSchema.get_config_schema()

        assert "properties" in schema
        assert "version" in schema["properties"]
        assert "settings" in schema["properties"]
        assert "handlers" in schema["properties"]

    def test_schema_version_has_pattern(self) -> None:
        """Should specify version format pattern."""
        schema = ConfigSchema.get_config_schema()

        version_spec = schema["properties"]["version"]
        assert "pattern" in version_spec
        # Should enforce major.minor format

    def test_schema_settings_defines_logging_enum(self) -> None:
        """Should define logging level enum values."""
        schema = ConfigSchema.get_config_schema()

        settings_spec = schema["properties"]["settings"]
        logging_level_spec = settings_spec["properties"]["logging_level"]

        assert "enum" in logging_level_spec
        assert set(logging_level_spec["enum"]) == {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }


class TestConfigSchemaErrorMessages:
    """Test error message quality and clarity."""

    def test_validation_error_includes_field_name(self) -> None:
        """Should include field name in validation error."""
        config: dict[str, Any] = {}  # Missing version

        try:
            ConfigSchema.validate_config(config)
            pytest.fail("Should have raised ValueError")
        except ValueError as e:
            # Error message should indicate what's wrong
            error_msg = str(e).lower()
            assert "version" in error_msg or "required" in error_msg

    def test_validation_error_includes_invalid_value(self) -> None:
        """Should include invalid value in error message."""
        config: dict[str, Any] = {"version": "1.0", "settings": {"logging_level": "INVALID"}}

        try:
            ConfigSchema.validate_config(config)
            pytest.fail("Should have raised ValueError")
        except ValueError as e:
            error_msg = str(e).lower()
            # Should mention the invalid value or the valid options
            assert "invalid" in error_msg or "enum" in error_msg or "logging" in error_msg

    def test_validation_error_for_wrong_type(self) -> None:
        """Should provide clear error for wrong type."""
        config: dict[str, Any] = {"version": 1.0}  # Should be string

        try:
            ConfigSchema.validate_config(config)
            pytest.fail("Should have raised ValueError")
        except ValueError as e:
            error_msg = str(e).lower()
            assert "type" in error_msg or "string" in error_msg
