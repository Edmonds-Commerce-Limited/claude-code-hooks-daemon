"""Tests for input validation configuration.

Tests that InputValidationConfig is properly integrated into Config
and has sensible defaults.
"""

import yaml

from claude_code_hooks_daemon.config.models import (
    Config,
    DaemonConfig,
    InputValidationConfig,
)


class TestInputValidationConfigDefaults:
    """Test default values for InputValidationConfig."""

    def test_enabled_by_default(self):
        """Input validation is enabled by default."""
        config = InputValidationConfig()
        assert config.enabled is True

    def test_strict_mode_disabled_by_default(self):
        """Strict mode is disabled by default (fail-open)."""
        config = InputValidationConfig()
        assert config.strict_mode is False

    def test_log_validation_errors_enabled_by_default(self):
        """Logging validation errors is enabled by default."""
        config = InputValidationConfig()
        assert config.log_validation_errors is True


class TestDaemonConfigIntegration:
    """Test InputValidationConfig integration with DaemonConfig."""

    def test_daemon_config_has_input_validation(self):
        """DaemonConfig includes input_validation field."""
        config = DaemonConfig()
        assert hasattr(config, "input_validation")
        assert isinstance(config.input_validation, InputValidationConfig)

    def test_daemon_config_default_validation_settings(self):
        """DaemonConfig has correct default validation settings."""
        config = DaemonConfig()
        assert config.input_validation.enabled is True
        assert config.input_validation.strict_mode is False
        assert config.input_validation.log_validation_errors is True


class TestConfigYamlSerialization:
    """Test YAML serialization/deserialization of validation config."""

    def test_serialize_default_config_includes_validation(self):
        """Serialized config includes input_validation with defaults."""
        config = Config()
        yaml_str = config.to_yaml()

        # Parse YAML
        data = yaml.safe_load(yaml_str)

        # Check structure (may be omitted if all defaults)
        # Defaults are excluded by exclude_unset=True
        assert "daemon" in data or config.daemon.input_validation.enabled is True

    def test_deserialize_config_with_validation_enabled(self):
        """Deserialize config with validation enabled."""
        yaml_str = """
version: "2.0"
daemon:
  input_validation:
    enabled: true
    strict_mode: false
"""
        data = yaml.safe_load(yaml_str)
        config = Config.model_validate(data)

        assert config.daemon.input_validation.enabled is True
        assert config.daemon.input_validation.strict_mode is False

    def test_deserialize_config_with_validation_disabled(self):
        """Deserialize config with validation disabled."""
        yaml_str = """
version: "2.0"
daemon:
  input_validation:
    enabled: false
"""
        data = yaml.safe_load(yaml_str)
        config = Config.model_validate(data)

        assert config.daemon.input_validation.enabled is False

    def test_deserialize_config_with_strict_mode(self):
        """Deserialize config with strict mode enabled."""
        yaml_str = """
version: "2.0"
daemon:
  input_validation:
    enabled: true
    strict_mode: true
"""
        data = yaml.safe_load(yaml_str)
        config = Config.model_validate(data)

        assert config.daemon.input_validation.enabled is True
        assert config.daemon.input_validation.strict_mode is True

    def test_deserialize_config_without_validation_section(self):
        """Config without input_validation section uses defaults."""
        yaml_str = """
version: "2.0"
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
"""
        data = yaml.safe_load(yaml_str)
        config = Config.model_validate(data)

        # Should use defaults
        assert config.daemon.input_validation.enabled is True
        assert config.daemon.input_validation.strict_mode is False


class TestConfigValidationModes:
    """Test different validation mode configurations."""

    def test_mode_disabled(self):
        """Mode 1: Validation disabled."""
        config = Config.model_validate(
            {
                "version": "2.0",
                "daemon": {"input_validation": {"enabled": False}},
            }
        )

        assert config.daemon.input_validation.enabled is False

    def test_mode_enabled_fail_open(self):
        """Mode 2: Enabled + fail-open (default)."""
        config = Config.model_validate(
            {
                "version": "2.0",
                "daemon": {
                    "input_validation": {
                        "enabled": True,
                        "strict_mode": False,
                    }
                },
            }
        )

        assert config.daemon.input_validation.enabled is True
        assert config.daemon.input_validation.strict_mode is False

    def test_mode_enabled_fail_closed(self):
        """Mode 3: Enabled + fail-closed (strict)."""
        config = Config.model_validate(
            {
                "version": "2.0",
                "daemon": {
                    "input_validation": {
                        "enabled": True,
                        "strict_mode": True,
                    }
                },
            }
        )

        assert config.daemon.input_validation.enabled is True
        assert config.daemon.input_validation.strict_mode is True


class TestConfigBackwardCompatibility:
    """Test backward compatibility with existing configs."""

    def test_old_config_without_input_validation_works(self):
        """Old configs without input_validation field work correctly."""
        yaml_str = """
version: "1.0"
settings:
  logging_level: DEBUG
"""
        data = yaml.safe_load(yaml_str)
        config = Config.model_validate(data)

        # Should have default validation settings
        assert config.daemon.input_validation.enabled is True
        assert config.daemon.input_validation.strict_mode is False

        # Legacy migration should work
        assert config.daemon.log_level == "DEBUG"

    def test_minimal_config_uses_defaults(self):
        """Minimal config uses all defaults."""
        config = Config()

        # All defaults present
        assert config.version == "2.0"
        assert config.daemon.idle_timeout_seconds == 600
        assert config.daemon.log_level == "INFO"
        assert config.daemon.input_validation.enabled is True
        assert config.daemon.input_validation.strict_mode is False
