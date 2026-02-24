"""Unit tests for config/validator.py - exhaustive validation testing.

Test Driven Development: Tests written to cover all validation branches.
"""

import pytest

from claude_code_hooks_daemon.config.validator import ConfigValidator, ValidationError


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_validation_error_is_exception(self) -> None:
        """ValidationError should be an Exception subclass."""
        error = ValidationError("Test error")
        assert isinstance(error, Exception)

    def test_validation_error_message(self) -> None:
        """ValidationError should preserve message."""
        error = ValidationError("Config validation failed")
        assert str(error) == "Config validation failed"


class TestConfigValidatorConstants:
    """Tests for ConfigValidator class constants."""

    def test_valid_event_types(self) -> None:
        """VALID_EVENT_TYPES should contain all 11 event types."""
        assert len(ConfigValidator.VALID_EVENT_TYPES) == 11
        assert "pre_tool_use" in ConfigValidator.VALID_EVENT_TYPES
        assert "post_tool_use" in ConfigValidator.VALID_EVENT_TYPES
        assert "permission_request" in ConfigValidator.VALID_EVENT_TYPES
        assert "notification" in ConfigValidator.VALID_EVENT_TYPES
        assert "user_prompt_submit" in ConfigValidator.VALID_EVENT_TYPES
        assert "session_start" in ConfigValidator.VALID_EVENT_TYPES
        assert "session_end" in ConfigValidator.VALID_EVENT_TYPES
        assert "stop" in ConfigValidator.VALID_EVENT_TYPES
        assert "subagent_stop" in ConfigValidator.VALID_EVENT_TYPES
        assert "pre_compact" in ConfigValidator.VALID_EVENT_TYPES
        assert "status_line" in ConfigValidator.VALID_EVENT_TYPES

    def test_valid_log_levels(self) -> None:
        """VALID_LOG_LEVELS should contain standard log levels."""
        assert len(ConfigValidator.VALID_LOG_LEVELS) == 4
        assert "DEBUG" in ConfigValidator.VALID_LOG_LEVELS
        assert "INFO" in ConfigValidator.VALID_LOG_LEVELS
        assert "WARNING" in ConfigValidator.VALID_LOG_LEVELS
        assert "ERROR" in ConfigValidator.VALID_LOG_LEVELS

    def test_priority_range(self) -> None:
        """Priority range should be 5-60."""
        assert ConfigValidator.MIN_PRIORITY == 5
        assert ConfigValidator.MAX_PRIORITY == 60

    def test_handler_name_pattern(self) -> None:
        """HANDLER_NAME_PATTERN should match valid snake_case names."""
        pattern = ConfigValidator.HANDLER_NAME_PATTERN
        assert pattern.match("handler")
        assert pattern.match("my_handler")
        assert pattern.match("handler_123")
        assert pattern.match("handler2")
        assert not pattern.match("Handler")
        assert not pattern.match("MyHandler")
        assert not pattern.match("123handler")
        assert not pattern.match("_handler")

    def test_version_pattern(self) -> None:
        """VERSION_PATTERN should match X.Y format."""
        pattern = ConfigValidator.VERSION_PATTERN
        assert pattern.match("1.0")
        assert pattern.match("2.1")
        assert pattern.match("10.5")
        assert not pattern.match("1")
        assert not pattern.match("1.0.0")
        assert not pattern.match("v1.0")


class TestValidateVersion:
    """Tests for version field validation."""

    def test_valid_version(self) -> None:
        """Valid version should pass validation."""
        config = {"version": "1.0"}
        errors = ConfigValidator._validate_version(config)
        assert errors == []

    def test_missing_version(self) -> None:
        """Missing version should return error."""
        config = {}
        errors = ConfigValidator._validate_version(config)
        assert len(errors) == 1
        assert "Missing required field: version" in errors[0]

    def test_version_wrong_type(self) -> None:
        """Version with wrong type should return error."""
        config = {"version": 1.0}
        errors = ConfigValidator._validate_version(config)
        assert len(errors) == 1
        assert "must be string" in errors[0]
        assert "float" in errors[0]

    def test_version_wrong_type_int(self) -> None:
        """Version as integer should return error."""
        config = {"version": 1}
        errors = ConfigValidator._validate_version(config)
        assert len(errors) == 1
        assert "must be string" in errors[0]
        assert "int" in errors[0]

    def test_version_invalid_format(self) -> None:
        """Version with invalid format should return error."""
        config = {"version": "1.0.0"}
        errors = ConfigValidator._validate_version(config)
        assert len(errors) == 1
        assert "invalid format" in errors[0]
        assert "1.0.0" in errors[0]

    def test_version_invalid_format_no_dot(self) -> None:
        """Version without dot should return error."""
        config = {"version": "1"}
        errors = ConfigValidator._validate_version(config)
        assert len(errors) == 1
        assert "invalid format" in errors[0]


class TestValidateDaemon:
    """Tests for daemon section validation."""

    def test_valid_daemon_section(self) -> None:
        """Valid daemon section should pass validation."""
        config = {
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
            }
        }
        errors = ConfigValidator._validate_daemon(config)
        assert errors == []

    def test_missing_daemon_section(self) -> None:
        """Missing daemon section should return error."""
        config = {}
        errors = ConfigValidator._validate_daemon(config)
        assert len(errors) == 1
        assert "Missing required section: daemon" in errors[0]

    def test_daemon_wrong_type(self) -> None:
        """Daemon section with wrong type should return error."""
        config = {"daemon": "not a dict"}
        errors = ConfigValidator._validate_daemon(config)
        assert len(errors) == 1
        assert "must be dictionary" in errors[0]
        assert "str" in errors[0]

    def test_daemon_wrong_type_list(self) -> None:
        """Daemon section as list should return error."""
        config = {"daemon": []}
        errors = ConfigValidator._validate_daemon(config)
        assert len(errors) == 1
        assert "must be dictionary" in errors[0]
        assert "list" in errors[0]

    def test_missing_idle_timeout(self) -> None:
        """Missing idle_timeout_seconds should return error."""
        config = {"daemon": {"log_level": "INFO"}}
        errors = ConfigValidator._validate_daemon(config)
        assert len(errors) == 1
        assert "idle_timeout_seconds" in errors[0]

    def test_idle_timeout_wrong_type(self) -> None:
        """idle_timeout_seconds with wrong type should return error."""
        config = {"daemon": {"idle_timeout_seconds": "600", "log_level": "INFO"}}
        errors = ConfigValidator._validate_daemon(config)
        assert len(errors) == 1
        assert "idle_timeout_seconds" in errors[0]
        assert "must be integer" in errors[0]
        assert "str" in errors[0]

    def test_idle_timeout_negative(self) -> None:
        """Negative idle_timeout_seconds should return error."""
        config = {"daemon": {"idle_timeout_seconds": -1, "log_level": "INFO"}}
        errors = ConfigValidator._validate_daemon(config)
        assert len(errors) == 1
        assert "must be positive integer" in errors[0]

    def test_idle_timeout_zero(self) -> None:
        """Zero idle_timeout_seconds should return error."""
        config = {"daemon": {"idle_timeout_seconds": 0, "log_level": "INFO"}}
        errors = ConfigValidator._validate_daemon(config)
        assert len(errors) == 1
        assert "must be positive integer" in errors[0]

    def test_missing_log_level(self) -> None:
        """Missing log_level should return error."""
        config = {"daemon": {"idle_timeout_seconds": 600}}
        errors = ConfigValidator._validate_daemon(config)
        assert len(errors) == 1
        assert "log_level" in errors[0]

    def test_log_level_wrong_type(self) -> None:
        """log_level with wrong type should return error."""
        config = {"daemon": {"idle_timeout_seconds": 600, "log_level": 10}}
        errors = ConfigValidator._validate_daemon(config)
        assert len(errors) == 1
        assert "log_level" in errors[0]
        assert "must be string" in errors[0]
        assert "int" in errors[0]

    def test_log_level_invalid_value(self) -> None:
        """log_level with invalid value should return error."""
        config = {"daemon": {"idle_timeout_seconds": 600, "log_level": "TRACE"}}
        errors = ConfigValidator._validate_daemon(config)
        assert len(errors) == 1
        assert "invalid value" in errors[0]
        assert "TRACE" in errors[0]
        assert "DEBUG" in errors[0]
        assert "INFO" in errors[0]

    def test_daemon_multiple_errors(self) -> None:
        """Daemon section with multiple errors should return all errors."""
        config = {"daemon": {"idle_timeout_seconds": -1, "log_level": "INVALID"}}
        errors = ConfigValidator._validate_daemon(config)
        assert len(errors) == 2


class TestValidateHandlers:
    """Tests for handlers section validation."""

    def test_valid_handlers_section(self) -> None:
        """Valid handlers section should pass validation."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert errors == []

    def test_missing_handlers_section(self) -> None:
        """Missing handlers section should return error."""
        config = {}
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert len(errors) == 1
        assert "Missing required section: handlers" in errors[0]

    def test_handlers_wrong_type(self) -> None:
        """Handlers section with wrong type should return error."""
        config = {"handlers": []}
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert len(errors) == 1
        assert "must be dictionary" in errors[0]
        assert "list" in errors[0]

    def test_invalid_event_type(self) -> None:
        """Invalid event type should return error."""
        config = {
            "handlers": {
                "invalid_event": {
                    "some_handler": {"enabled": True},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert len(errors) == 1
        assert "Invalid event type" in errors[0]
        assert "invalid_event" in errors[0]
        assert "pre_tool_use" in errors[0]

    def test_event_handlers_wrong_type(self) -> None:
        """Event handlers with wrong type should return error."""
        config = {"handlers": {"pre_tool_use": []}}
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert len(errors) == 1
        assert "handlers.pre_tool_use" in errors[0]
        assert "must be dictionary" in errors[0]
        assert "list" in errors[0]

    def test_invalid_handler_name(self) -> None:
        """Invalid handler name should return error."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "InvalidHandlerName": {"enabled": True},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert len(errors) == 1
        assert "Invalid handler name" in errors[0]
        assert "InvalidHandlerName" in errors[0]
        assert "snake_case" in errors[0]

    def test_handler_config_wrong_type(self) -> None:
        """Handler config with wrong type should return error."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "my_handler": "not a dict",
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert len(errors) == 1
        assert "handlers.pre_tool_use.my_handler" in errors[0]
        assert "must be dictionary" in errors[0]
        assert "str" in errors[0]

    def test_enabled_wrong_type(self) -> None:
        """enabled field with wrong type should return error."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {"enabled": "true"},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert len(errors) == 1
        assert "enabled" in errors[0]
        assert "must be boolean" in errors[0]
        assert "str" in errors[0]

    def test_priority_none_value(self) -> None:
        """priority: null (None) in config should return error.

        Regression test for Plan 00070: PyYAML parses 'priority:' with no
        value as None, which crashed the daemon during handler chain sorting.
        """
        config = {
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {"enabled": True, "priority": None},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert len(errors) == 1
        assert "priority" in errors[0]
        assert "must be integer" in errors[0]
        assert "NoneType" in errors[0]

    def test_priority_wrong_type(self) -> None:
        """priority field with wrong type should return error."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {"priority": "10"},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert len(errors) == 1
        assert "priority" in errors[0]
        assert "must be integer" in errors[0]
        assert "str" in errors[0]

    def test_priority_too_low(self) -> None:
        """priority below minimum should return error."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {"priority": 1},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert len(errors) == 1
        assert "priority" in errors[0]
        assert "must be in range" in errors[0]
        assert "5-60" in errors[0]

    def test_priority_too_high(self) -> None:
        """priority above maximum should return error."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {"priority": 100},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert len(errors) == 1
        assert "priority" in errors[0]
        assert "must be in range" in errors[0]

    def test_duplicate_priorities(self) -> None:
        """Duplicate priorities should log warning but NOT return error."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "handler_one": {"priority": 10},
                    "handler_two": {"priority": 10},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        # Duplicate priorities are handled by HandlerChain with alphabetical tiebreaker
        # Not a validation error (per user feedback)
        assert len(errors) == 0

    def test_different_priorities_ok(self) -> None:
        """Different priorities should be valid."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "handler_one": {"priority": 10},
                    "handler_two": {"priority": 20},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert errors == []

    def test_enabled_field_optional(self) -> None:
        """enabled field should be optional."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {"priority": 10},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert errors == []

    def test_priority_field_optional(self) -> None:
        """priority field should be optional."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {"enabled": True},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert errors == []


class TestValidatePlugins:
    """Tests for plugins section validation."""

    def test_valid_plugins_section(self) -> None:
        """Valid plugins section should pass validation."""
        config = {
            "plugins": {
                "paths": ["/path/to/plugins"],
                "plugins": [
                    {"path": "/path/to/plugin.py"},
                    {"path": "/another/plugin.py"},
                ],
            }
        }
        errors = ConfigValidator._validate_plugins(config)
        assert errors == []

    def test_missing_plugins_section(self) -> None:
        """Missing plugins section should be valid (optional)."""
        config = {}
        errors = ConfigValidator._validate_plugins(config)
        assert errors == []

    def test_plugins_wrong_type(self) -> None:
        """Plugins section with wrong type should return error."""
        config = {"plugins": "not a dict"}
        errors = ConfigValidator._validate_plugins(config)
        assert len(errors) == 1
        assert "plugins" in errors[0]
        assert "must be dictionary" in errors[0]
        assert "str" in errors[0]

    def test_plugins_paths_wrong_type(self) -> None:
        """Plugins paths with wrong type should return error."""
        config = {"plugins": {"paths": "not a list"}}
        errors = ConfigValidator._validate_plugins(config)
        assert len(errors) == 1
        assert "plugins.paths" in errors[0]
        assert "must be list" in errors[0]

    def test_plugin_wrong_type(self) -> None:
        """Plugin entry with wrong type should return error."""
        config = {"plugins": {"plugins": ["not a dict"]}}
        errors = ConfigValidator._validate_plugins(config)
        assert len(errors) == 1
        assert "plugins.plugins[0]" in errors[0]
        assert "must be dictionary" in errors[0]
        assert "str" in errors[0]

    def test_plugin_missing_path(self) -> None:
        """Plugin without path should return error."""
        config = {"plugins": {"plugins": [{"name": "my-plugin"}]}}
        errors = ConfigValidator._validate_plugins(config)
        assert len(errors) == 1
        assert "Missing required field: plugins.plugins[0].path" in errors[0]

    def test_multiple_plugin_errors(self) -> None:
        """Multiple plugin errors should return all errors."""
        config = {
            "plugins": {
                "plugins": [
                    {},
                    {"path": "/valid/path"},
                    "not a dict",
                ],
            }
        }
        errors = ConfigValidator._validate_plugins(config)
        assert len(errors) == 2


class TestValidate:
    """Tests for main validate() method."""

    def test_valid_config(self) -> None:
        """Fully valid config should pass validation."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
            },
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                }
            },
        }
        errors = ConfigValidator.validate(config, validate_handler_names=False)
        assert errors == []

    def test_config_with_plugins(self) -> None:
        """Valid config with plugins should pass validation."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
            },
            "handlers": {},
            "plugins": {"paths": [], "plugins": [{"path": "/path/to/plugin.py"}]},
        }
        errors = ConfigValidator.validate(config, validate_handler_names=False)
        assert errors == []

    def test_multiple_errors_from_different_sections(self) -> None:
        """Errors from multiple sections should all be returned."""
        config = {
            "version": 1,  # Wrong type
            "daemon": {
                "idle_timeout_seconds": -1,  # Invalid value
                "log_level": "INVALID",  # Invalid value
            },
            "handlers": {
                "invalid_event": {},  # Invalid event type
            },
        }
        errors = ConfigValidator.validate(config, validate_handler_names=False)
        assert len(errors) >= 4

    def test_empty_config(self) -> None:
        """Empty config should return multiple errors."""
        config = {}
        errors = ConfigValidator.validate(config, validate_handler_names=False)
        assert len(errors) >= 3  # version, daemon, handlers all missing


class TestValidateAndRaise:
    """Tests for validate_and_raise() method."""

    def test_valid_config_no_exception(self) -> None:
        """Valid config should not raise exception."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
            },
            "handlers": {},
        }
        ConfigValidator.validate_and_raise(config)  # Should not raise

    def test_invalid_config_raises_exception(self) -> None:
        """Invalid config should raise ValidationError."""
        config = {"version": 1}
        with pytest.raises(ValidationError):
            ConfigValidator.validate_and_raise(config)

    def test_exception_contains_error_count(self) -> None:
        """ValidationError should contain error count."""
        config = {"version": 1}
        with pytest.raises(ValidationError) as exc_info:
            ConfigValidator.validate_and_raise(config)
        assert "error(s)" in str(exc_info.value)

    def test_exception_contains_error_list(self) -> None:
        """ValidationError should contain list of errors."""
        config = {"version": 1}
        with pytest.raises(ValidationError) as exc_info:
            ConfigValidator.validate_and_raise(config)
        assert "must be string" in str(exc_info.value)


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_minimum_valid_priority(self) -> None:
        """Priority of 5 (minimum) should be valid."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {"priority": 5},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert errors == []

    def test_maximum_valid_priority(self) -> None:
        """Priority of 60 (maximum) should be valid."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "my_handler": {"priority": 60},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert errors == []

    def test_all_log_levels_valid(self) -> None:
        """All valid log levels should pass validation."""
        for log_level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            config = {"daemon": {"idle_timeout_seconds": 600, "log_level": log_level}}
            errors = ConfigValidator._validate_daemon(config)
            assert errors == []

    def test_all_event_types_valid(self) -> None:
        """All valid event types should pass validation."""
        event_types = [
            "pre_tool_use",
            "post_tool_use",
            "permission_request",
            "notification",
            "user_prompt_submit",
            "session_start",
            "session_end",
            "stop",
            "subagent_stop",
            "pre_compact",
        ]
        for event_type in event_types:
            config = {"handlers": {event_type: {}}}
            errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
            assert errors == []

    def test_handler_name_with_numbers(self) -> None:
        """Handler name with numbers should be valid."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "handler_123": {"enabled": True},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert errors == []

    def test_handler_name_single_char(self) -> None:
        """Handler name with single character should be valid."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "h": {"enabled": True},
                }
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert errors == []

    def test_empty_handlers_per_event(self) -> None:
        """Empty handlers dict per event should be valid."""
        config = {
            "handlers": {
                "pre_tool_use": {},
                "post_tool_use": {},
            }
        }
        errors = ConfigValidator._validate_handlers(config, validate_handler_names=False)
        assert errors == []

    def test_empty_plugins_section(self) -> None:
        """Empty plugins section should be valid."""
        config = {"plugins": {"paths": [], "plugins": []}}
        errors = ConfigValidator._validate_plugins(config)
        assert errors == []

    def test_plugins_dict_with_no_subkeys(self) -> None:
        """Plugins dict with no subkeys should be valid (defaults apply)."""
        config = {"plugins": {}}
        errors = ConfigValidator._validate_plugins(config)
        assert errors == []


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
