"""Tests for handler name validation in config.

Following TDD - these tests verify that config validation catches typos
in handler names and fails fast with clear error messages.

CRITICAL: This addresses the bug where users could typo handler names
(e.g., 'destructive_git' instead of 'destructive_git_handler') and the
config would silently be ignored, with no error message.
"""

import pytest

from claude_code_hooks_daemon.config.validator import ConfigValidator, ValidationError


class TestHandlerNameValidation:
    """Test that config validator catches handler name typos."""

    def test_valid_handler_name_passes_validation(self) -> None:
        """Test that correct handler names pass validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {"pre_tool_use": {"destructive_git_handler": {"enabled": True}}},
        }

        # Should not raise - this is a valid handler name
        ConfigValidator.validate_and_raise(config)

    def test_typo_in_handler_name_fails_validation(self) -> None:
        """Test that typos in handler names are caught.

        CRITICAL: This would have caught the markdown_organization bug.
        """
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    # TYPO: Missing _handler suffix
                    "destructive_git": {"enabled": False}
                }
            },
        }

        # Should raise ValidationError with clear message
        with pytest.raises(ValidationError) as exc_info:
            ConfigValidator.validate_and_raise(config)

        error_message = str(exc_info.value)
        assert "destructive_git" in error_message.lower()
        assert "unknown handler" in error_message.lower() or "not found" in error_message.lower()

    def test_multiple_invalid_handler_names_all_reported(self) -> None:
        """Test that all invalid handler names are reported, not just first."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True},  # TYPO
                    "sed_blocker": {"enabled": True},  # TYPO
                }
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            ConfigValidator.validate_and_raise(config)

        error_message = str(exc_info.value)
        # Both typos should be mentioned
        assert "destructive_git" in error_message.lower()
        assert "sed_blocker" in error_message.lower()

    def test_mixed_valid_and_invalid_handler_names(self) -> None:
        """Test that only invalid names are reported when mixed with valid ones."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git_handler": {"enabled": True},  # VALID
                    "typo_handler": {"enabled": True},  # INVALID
                }
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            ConfigValidator.validate_and_raise(config)

        error_message = str(exc_info.value)
        # Only invalid name should be mentioned
        assert "typo_handler" in error_message.lower()
        assert "destructive_git_handler" not in error_message.lower()

    def test_validation_suggests_similar_handler_names(self) -> None:
        """Test that validation suggests similar handler names for typos."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    # Close to destructive_git_handler
                    "destructive_git": {"enabled": False}
                }
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            ConfigValidator.validate_and_raise(config)

        error_message = str(exc_info.value)
        # Should suggest the correct name
        assert "destructive_git_handler" in error_message.lower()
        assert "did you mean" in error_message.lower() or "suggestion" in error_message.lower()

    def test_validation_checks_all_event_types(self) -> None:
        """Test that handler name validation works for all event types."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {"invalid_pre": {"enabled": True}},
                "post_tool_use": {"invalid_post": {"enabled": True}},
                "session_start": {"invalid_session": {"enabled": True}},
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            ConfigValidator.validate_and_raise(config)

        error_message = str(exc_info.value)
        # All invalid handlers should be reported
        assert "invalid_pre" in error_message.lower()
        assert "invalid_post" in error_message.lower()
        assert "invalid_session" in error_message.lower()

    def test_empty_handlers_section_passes(self) -> None:
        """Test that empty handlers sections pass validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {"pre_tool_use": {}},
        }

        # Should not raise
        ConfigValidator.validate_and_raise(config)

    def test_validation_provides_list_of_valid_handlers(self) -> None:
        """Test that error message includes available handlers for the event type."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {"pre_tool_use": {"nonexistent_handler": {"enabled": True}}},
        }

        with pytest.raises(ValidationError) as exc_info:
            ConfigValidator.validate_and_raise(config)

        error_message = str(exc_info.value)
        # Should list some available handlers
        assert "available" in error_message.lower() or "valid" in error_message.lower()


class TestHandlerNameValidationPerformance:
    """Test that handler name validation doesn't impact performance."""

    def test_validation_completes_quickly_with_many_handlers(self) -> None:
        """Test that validation is fast even with many handlers configured."""
        import time

        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git_handler": {"enabled": True},
                    "sed_blocker_handler": {"enabled": True},
                    "absolute_path_handler": {"enabled": True},
                    "tdd_enforcement_handler": {"enabled": True},
                    "british_english_handler": {"enabled": True},
                }
            },
        }

        start = time.perf_counter()
        ConfigValidator.validate_and_raise(config)
        elapsed = time.perf_counter() - start

        # Should complete in under 100ms
        assert elapsed < 0.1, f"Validation took {elapsed:.3f}s, expected < 0.1s"


class TestHandlerDiscoveryForValidation:
    """Test handler discovery mechanism used for validation."""

    def test_validator_discovers_all_production_handlers(self) -> None:
        """Test that validator can discover all production handlers."""
        from claude_code_hooks_daemon.config.validator import ConfigValidator

        # Validator should have access to all handler names
        pre_tool_use_handlers = ConfigValidator.get_available_handlers("pre_tool_use")

        # Should include known production handlers
        assert "destructive_git_handler" in pre_tool_use_handlers
        assert "sed_blocker_handler" in pre_tool_use_handlers
        assert "absolute_path_handler" in pre_tool_use_handlers

    def test_validator_discovers_handlers_for_all_events(self) -> None:
        """Test that validator can discover handlers for all event types."""
        from claude_code_hooks_daemon.config.validator import ConfigValidator

        event_types = [
            "pre_tool_use",
            "post_tool_use",
            "session_start",
            "session_end",
            "pre_compact",
            "user_prompt_submit",
            "stop",
            "subagent_stop",
            "notification",
            "permission_request",
        ]

        for event_type in event_types:
            handlers = ConfigValidator.get_available_handlers(event_type)
            # Should be a set of strings
            assert isinstance(handlers, set)
            # Some events might have no handlers (that's ok)
            assert len(handlers) >= 0
