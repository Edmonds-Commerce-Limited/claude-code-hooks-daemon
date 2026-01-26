"""Tests for server startup validation."""

from claude_code_hooks_daemon.config.validator import ValidationError


class TestServerStartupValidation:
    """Test that server validates configuration on startup."""

    def test_server_startup_with_valid_config(self):
        """Test that server starts with valid configuration."""
        # This test will be implemented when server module loads config
        # For now, we test that validation would pass
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
            },
            "handlers": {
                "pre_tool_use": {},
            },
        }

        from claude_code_hooks_daemon.config.validator import ConfigValidator

        errors = ConfigValidator.validate(config)
        assert errors == []

    def test_server_refuses_invalid_config(self):
        """Test that server refuses to start with invalid configuration."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": -1,  # Invalid
                "log_level": "INFO",
            },
            "handlers": {
                "pre_tool_use": {},
            },
        }

        from claude_code_hooks_daemon.config.validator import ConfigValidator

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0

    def test_validation_error_message_is_helpful(self):
        """Test that validation error messages are helpful."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": "not_a_number",  # Wrong type
                "log_level": "INFO",
            },
            "handlers": {
                "pre_tool_use": {},
            },
        }

        from claude_code_hooks_daemon.config.validator import ConfigValidator

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        # Should mention the field name and expected type
        assert any("idle_timeout" in err.lower() for err in errors)
        assert any("integer" in err.lower() for err in errors)

    def test_validate_and_raise_method(self):
        """Test that validate_and_raise raises ValidationError on invalid config."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": -1,
                "log_level": "INFO",
            },
            "handlers": {},
        }

        from claude_code_hooks_daemon.config.validator import (
            ConfigValidator,
        )

        try:
            ConfigValidator.validate_and_raise(config)
            raise AssertionError("Should have raised ValidationError")
        except ValidationError as e:
            # Error message should be helpful
            assert "idle_timeout" in str(e).lower()
            assert "error" in str(e).lower()  # Should mention error count

    def test_validate_and_raise_with_valid_config(self):
        """Test that validate_and_raise does not raise on valid config."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
            },
            "handlers": {
                "pre_tool_use": {},
            },
        }

        from claude_code_hooks_daemon.config.validator import ConfigValidator

        # Should not raise
        ConfigValidator.validate_and_raise(config)
