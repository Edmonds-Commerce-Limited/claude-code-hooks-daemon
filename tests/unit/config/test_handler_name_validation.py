"""Tests for handler name validation in config.

Following TDD - these tests verify that config validation catches typos
in handler names and fails fast with clear error messages.

CRITICAL: This addresses the bug where users could typo handler names
and the config would silently be ignored, with no error message.

NOTE: Handler config keys do NOT include _handler suffix.
Class DestructiveGitHandler -> config key "destructive_git"
"""

import pytest

from claude_code_hooks_daemon.config.validator import ConfigValidator, ValidationError
from claude_code_hooks_daemon.constants import RETIRED_HANDLERS


class TestRetiredHandlerNames:
    """A REMOVED handler's config key must not degrade a client's daemon.

    Plan 00233. When `transcript_archiver` was deleted, every client config
    still naming it put the daemon into DEGRADED MODE on every session — a
    handler removal is not a user error, and the user cannot act on it until
    they read an upgrade note. Retired names are therefore accepted and
    reported through the upgrade manifests instead.

    The second test is the important one: this must not become a hole that
    swallows genuine typos, which is the whole reason name validation exists.
    """

    def test_retired_handler_key_does_not_error(self) -> None:
        """A config still naming a removed handler validates cleanly."""
        retired_name = next(iter(RETIRED_HANDLERS))
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {"pre_compact": {retired_name: {"enabled": True, "priority": 10}}},
        }

        ConfigValidator.validate_and_raise(config)

    def test_retired_registry_is_not_empty(self) -> None:
        """Guard the guard — an empty registry would make the test above vacuous."""
        assert RETIRED_HANDLERS
        assert all(isinstance(reason, str) and reason for reason in RETIRED_HANDLERS.values())

    def test_typos_are_still_caught(self) -> None:
        """Retirement must not weaken typo detection."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {"pre_tool_use": {"destructive_git_handler": {"enabled": False}}},
        }

        with pytest.raises(ValidationError):
            ConfigValidator.validate_and_raise(config)

    def test_retired_name_under_the_wrong_event_is_still_accepted(self) -> None:
        """Retirement is by NAME, not by event.

        A client may have had the key under any event section, and after
        removal there is no correct event to check it against — the handler
        no longer exists anywhere.
        """
        retired_name = next(iter(RETIRED_HANDLERS))
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {"pre_tool_use": {retired_name: {"enabled": True}}},
        }

        ConfigValidator.validate_and_raise(config)


class TestHandlerNameValidation:
    """Test that config validator catches handler name typos."""

    def test_valid_handler_name_passes_validation(self) -> None:
        """Test that correct handler names pass validation."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True}}},
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
                    # TYPO: Wrong name with unexpected suffix
                    "destructive_git_handler": {"enabled": False}
                }
            },
        }

        # Should raise ValidationError with clear message
        with pytest.raises(ValidationError) as exc_info:
            ConfigValidator.validate_and_raise(config)

        error_message = str(exc_info.value)
        assert "destructive_git_handler" in error_message.lower()
        assert "unknown handler" in error_message.lower() or "not found" in error_message.lower()

    def test_multiple_invalid_handler_names_all_reported(self) -> None:
        """Test that all invalid handler names are reported, not just first."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "invalid_name_one": {"enabled": True},  # TYPO
                    "invalid_name_two": {"enabled": True},  # TYPO
                }
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            ConfigValidator.validate_and_raise(config)

        error_message = str(exc_info.value)
        # Both typos should be mentioned
        assert "invalid_name_one" in error_message.lower()
        assert "invalid_name_two" in error_message.lower()

    def test_mixed_valid_and_invalid_handler_names(self) -> None:
        """Test that only invalid names are reported when mixed with valid ones."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True},  # VALID
                    "typo_name": {"enabled": True},  # INVALID
                }
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            ConfigValidator.validate_and_raise(config)

        error_message = str(exc_info.value)
        # Invalid name should be mentioned as unknown
        assert "typo_name" in error_message.lower()
        assert "unknown handler" in error_message.lower()
        # Valid handler should not be mentioned as unknown (it may appear in available handlers list)
        assert "unknown handler 'destructive_git'" not in error_message.lower()

    def test_validation_suggests_similar_handler_names(self) -> None:
        """Test that validation suggests similar handler names for typos."""
        config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    # Typo: Close to destructive_git (correct)
                    "destructiv_git": {"enabled": False}
                }
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            ConfigValidator.validate_and_raise(config)

        error_message = str(exc_info.value)
        # Should suggest the correct name
        assert "destructive_git" in error_message.lower()
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
                    "destructive_git": {"enabled": True},
                    "sed_blocker": {"enabled": True},
                    "absolute_path": {"enabled": True},
                    "tdd_enforcement": {"enabled": True},
                    "british_english": {"enabled": True},
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

        # Should include known production handlers (without _handler suffix)
        assert "destructive_git" in pre_tool_use_handlers
        assert "sed_blocker" in pre_tool_use_handlers
        assert "absolute_path" in pre_tool_use_handlers

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
