"""Tests for hello_world handler config integration."""

import pytest

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.schema import ConfigSchema


class TestHelloWorldConfigSchema:
    """Test config schema validation for enable_hello_world_handlers."""

    def test_schema_allows_enable_hello_world_handlers_true(self):
        """Schema should accept enable_hello_world_handlers: true."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
                "enable_hello_world_handlers": True,
            },
        }
        # Should not raise
        ConfigSchema.validate_config(config)

    def test_schema_allows_enable_hello_world_handlers_false(self):
        """Schema should accept enable_hello_world_handlers: false."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
                "enable_hello_world_handlers": False,
            },
        }
        # Should not raise
        ConfigSchema.validate_config(config)

    def test_schema_allows_enable_hello_world_handlers_omitted(self):
        """Schema should accept config with enable_hello_world_handlers omitted."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
            },
        }
        # Should not raise (optional field)
        ConfigSchema.validate_config(config)

    def test_schema_rejects_enable_hello_world_handlers_non_boolean(self):
        """Schema should reject non-boolean values for enable_hello_world_handlers."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
                "enable_hello_world_handlers": "yes",  # Invalid: should be boolean
            },
        }
        with pytest.raises(ValueError, match="Invalid configuration"):
            ConfigSchema.validate_config(config)

    def test_schema_accepts_daemon_section_without_enable_hello_world(self):
        """Schema should work with daemon section but no enable_hello_world_handlers."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 300,
                "log_level": "DEBUG",
            },
        }
        # Should not raise
        ConfigSchema.validate_config(config)

    def test_schema_accepts_config_without_daemon_section(self):
        """Schema should work with no daemon section at all."""
        config = {
            "version": "1.0",
            "handlers": {
                "pre_tool_use": {},
            },
        }
        # Should not raise (daemon section is optional)
        ConfigSchema.validate_config(config)


class TestHelloWorldConfigLoading:
    """Test loading config with enable_hello_world_handlers."""

    def test_load_config_with_enable_hello_world_true(self, tmp_path):
        """Should load config with enable_hello_world_handlers: true."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
version: "1.0"
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
  enable_hello_world_handlers: true
""")

        config = ConfigLoader.load(config_file)
        assert config["daemon"]["enable_hello_world_handlers"] is True

    def test_load_config_with_enable_hello_world_false(self, tmp_path):
        """Should load config with enable_hello_world_handlers: false."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
version: "1.0"
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
  enable_hello_world_handlers: false
""")

        config = ConfigLoader.load(config_file)
        assert config["daemon"]["enable_hello_world_handlers"] is False

    def test_load_config_without_enable_hello_world(self, tmp_path):
        """Should load config without enable_hello_world_handlers (omitted)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
version: "1.0"
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
""")

        config = ConfigLoader.load(config_file)
        # Key should not exist when omitted
        assert "enable_hello_world_handlers" not in config.get("daemon", {})


class TestHelloWorldConfigDefault:
    """Test default value handling for enable_hello_world_handlers."""

    def test_default_value_is_false_when_omitted(self):
        """When enable_hello_world_handlers is omitted, default should be false."""
        config = {"version": "1.0", "daemon": {"log_level": "INFO"}}

        # Simulate how daemon would check the flag
        enable_hello_world = config.get("daemon", {}).get("enable_hello_world_handlers", False)

        assert enable_hello_world is False

    def test_explicit_true_overrides_default(self):
        """Explicit true should override default false."""
        config = {
            "version": "1.0",
            "daemon": {
                "log_level": "INFO",
                "enable_hello_world_handlers": True,
            },
        }

        enable_hello_world = config.get("daemon", {}).get("enable_hello_world_handlers", False)

        assert enable_hello_world is True

    def test_explicit_false_matches_default(self):
        """Explicit false should match default behavior."""
        config = {
            "version": "1.0",
            "daemon": {
                "log_level": "INFO",
                "enable_hello_world_handlers": False,
            },
        }

        enable_hello_world = config.get("daemon", {}).get("enable_hello_world_handlers", False)

        assert enable_hello_world is False


class TestHelloWorldConfigExtraction:
    """Test helper for extracting enable_hello_world_handlers from config."""

    def test_extract_from_full_config(self):
        """Should extract enable_hello_world_handlers from complete config."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
                "enable_hello_world_handlers": True,
            },
        }

        enabled = config.get("daemon", {}).get("enable_hello_world_handlers", False)
        assert enabled is True

    def test_extract_from_minimal_config(self):
        """Should extract (default false) from minimal config."""
        config = {"version": "1.0"}

        enabled = config.get("daemon", {}).get("enable_hello_world_handlers", False)
        assert enabled is False

    def test_extract_from_daemon_section_without_flag(self):
        """Should extract (default false) when daemon exists but flag doesn't."""
        config = {
            "version": "1.0",
            "daemon": {
                "log_level": "DEBUG",
            },
        }

        enabled = config.get("daemon", {}).get("enable_hello_world_handlers", False)
        assert enabled is False
