"""Tests for config validator."""

from claude_code_hooks_daemon.config.validator import ConfigValidator


class TestConfigValidator:
    """Test configuration validation."""

    def test_valid_minimal_config(self):
        """Test that minimal valid config passes validation."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 600,
                "log_level": "INFO",
            },
            "handlers": {
                "pre_tool_use": {},
                "post_tool_use": {},
                "permission_request": {},
                "notification": {},
                "user_prompt_submit": {},
                "session_start": {},
                "session_end": {},
                "stop": {},
                "subagent_stop": {},
                "pre_compact": {},
            },
        }

        # Should not raise
        errors = ConfigValidator.validate(config)
        assert errors == []

    def test_valid_config_with_handlers(self):
        """Test valid config with handler configuration."""
        config = {
            "version": "1.0",
            "daemon": {
                "idle_timeout_seconds": 300,
                "log_level": "DEBUG",
            },
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "git_stash": {"enabled": False, "priority": 20},
                },
                "post_tool_use": {},
                "permission_request": {},
                "notification": {},
                "user_prompt_submit": {},
                "session_start": {},
                "session_end": {},
                "stop": {},
                "subagent_stop": {},
                "pre_compact": {},
            },
        }

        errors = ConfigValidator.validate(config)
        assert errors == []

    def test_missing_version_field(self):
        """Test that missing version field fails validation."""
        config = {
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {"pre_tool_use": {}},
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("version" in err.lower() for err in errors)

    def test_invalid_version_format(self):
        """Test that invalid version format fails validation."""
        config = {
            "version": "1",  # Should be "X.Y"
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {"pre_tool_use": {}},
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("version" in err.lower() and "format" in err.lower() for err in errors)

    def test_invalid_log_level(self):
        """Test that invalid log_level fails validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INVALID"},
            "handlers": {"pre_tool_use": {}},
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("log_level" in err.lower() for err in errors)

    def test_valid_log_levels(self):
        """Test that all valid log levels are accepted."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]

        for level in valid_levels:
            config = {
                "version": "1.0",
                "daemon": {"idle_timeout_seconds": 600, "log_level": level},
                "handlers": {"pre_tool_use": {}},
            }
            errors = ConfigValidator.validate(config)
            assert errors == [], f"Log level {level} should be valid"

    def test_negative_idle_timeout(self):
        """Test that negative idle_timeout_seconds fails validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": -1, "log_level": "INFO"},
            "handlers": {"pre_tool_use": {}},
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("idle_timeout" in err.lower() and "positive" in err.lower() for err in errors)

    def test_zero_idle_timeout(self):
        """Test that zero idle_timeout_seconds fails validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 0, "log_level": "INFO"},
            "handlers": {"pre_tool_use": {}},
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("idle_timeout" in err.lower() for err in errors)

    def test_idle_timeout_wrong_type(self):
        """Test that string idle_timeout_seconds fails validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": "600", "log_level": "INFO"},
            "handlers": {"pre_tool_use": {}},
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("idle_timeout" in err.lower() and "integer" in err.lower() for err in errors)

    def test_enabled_wrong_type(self):
        """Test that non-boolean enabled value fails validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": "yes", "priority": 10},
                },
            },
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("enabled" in err.lower() and "boolean" in err.lower() for err in errors)

    def test_priority_out_of_range_low(self):
        """Test that priority < 5 fails validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 3},
                },
            },
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("priority" in err.lower() and "5-60" in err for err in errors)

    def test_priority_out_of_range_high(self):
        """Test that priority > 60 fails validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 65},
                },
            },
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("priority" in err.lower() and "5-60" in err for err in errors)

    def test_priority_wrong_type(self):
        """Test that string priority fails validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": "10"},
                },
            },
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("priority" in err.lower() and "integer" in err.lower() for err in errors)

    def test_duplicate_priorities_same_event(self):
        """Test that duplicate priorities within same event fail validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "git_stash": {"enabled": True, "priority": 10},  # Duplicate!
                },
            },
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("duplicate" in err.lower() and "priority" in err.lower() for err in errors)

    def test_duplicate_priorities_different_events_allowed(self):
        """Test that duplicate priorities across different events are allowed."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                },
                "post_tool_use": {
                    "some_handler": {
                        "enabled": True,
                        "priority": 10,
                    },  # Same priority, different event - OK
                },
            },
        }

        errors = ConfigValidator.validate(config)
        assert errors == []

    def test_invalid_event_type(self):
        """Test that invalid event type fails validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "invalid_event": {},  # Not a valid hook event
            },
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("invalid_event" in err.lower() for err in errors)

    def test_all_valid_event_types(self):
        """Test that all 10 valid event types are accepted."""
        valid_events = [
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

        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {event: {} for event in valid_events},
        }

        errors = ConfigValidator.validate(config)
        assert errors == []

    def test_invalid_handler_name_format(self):
        """Test that invalid handler name format fails validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "Invalid-Handler": {"enabled": True, "priority": 10},  # Hyphens not allowed
                },
            },
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("handler name" in err.lower() and "snake_case" in err.lower() for err in errors)

    def test_valid_handler_name_formats(self):
        """Test that valid snake_case handler names are accepted."""
        valid_names = [
            "simple",
            "two_words",
            "multiple_word_handler",
            "handler123",
            "handler_v2",
        ]

        for name in valid_names:
            config = {
                "version": "1.0",
                "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
                "handlers": {
                    "pre_tool_use": {
                        name: {"enabled": True, "priority": 10},
                    },
                },
            }
            errors = ConfigValidator.validate(config)
            assert errors == [], f"Handler name '{name}' should be valid"

    def test_missing_daemon_section(self):
        """Test that missing daemon section fails validation."""
        config = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {}},
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("daemon" in err.lower() for err in errors)

    def test_missing_handlers_section(self):
        """Test that missing handlers section fails validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        assert any("handlers" in err.lower() for err in errors)

    def test_plugins_section_optional(self):
        """Test that plugins section is optional."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {"pre_tool_use": {}},
        }

        errors = ConfigValidator.validate(config)
        assert errors == []

    def test_valid_plugins_section(self):
        """Test that valid plugins section is accepted."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {"pre_tool_use": {}},
            "plugins": [
                {"path": ".claude/hooks/custom", "handlers": ["custom_one"]},
            ],
        }

        errors = ConfigValidator.validate(config)
        assert errors == []

    def test_multiple_validation_errors(self):
        """Test that multiple errors are all reported."""
        config = {
            "version": "1",  # Invalid format
            "daemon": {
                "idle_timeout_seconds": -1,  # Invalid (negative)
                "log_level": "INVALID",  # Invalid level
            },
            "handlers": {
                "invalid_event": {},  # Invalid event type
                "pre_tool_use": {
                    "bad-name": {"enabled": "yes", "priority": 100},  # Multiple errors
                },
            },
        }

        errors = ConfigValidator.validate(config)
        # Should report multiple errors
        assert len(errors) >= 4

    def test_handler_config_additional_fields_allowed(self):
        """Test that additional fields in handler config are allowed (forward compatibility)."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "git_stash": {
                        "enabled": True,
                        "priority": 20,
                        "escape_hatch": "CONFIRMED",  # Additional field
                        "custom_option": "value",  # Additional field
                    },
                },
            },
        }

        errors = ConfigValidator.validate(config)
        assert errors == []

    def test_validation_error_includes_context(self):
        """Test that validation errors include helpful context."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 100},
                },
            },
        }

        errors = ConfigValidator.validate(config)
        assert len(errors) > 0
        # Should mention handler name and path
        assert any("destructive_git" in err for err in errors)
        assert any("pre_tool_use" in err for err in errors)
