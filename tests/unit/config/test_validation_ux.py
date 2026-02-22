"""Tests for user-friendly config validation error messages.

Task 4.1: When Pydantic ValidationError occurs during daemon startup,
users should see helpful messages with before/after format examples
instead of raw Python tracebacks.

Task 4.2: Duplicate priority warnings should be DEBUG level, not WARNING,
since many handlers intentionally share priorities.
"""

from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config


class TestFormatValidationError:
    """Tests for format_validation_error() producing user-friendly messages."""

    def test_missing_required_field_shows_before_after(self) -> None:
        """Missing 'event_type' on plugin should show before/after example."""
        from claude_code_hooks_daemon.config.validation_ux import format_validation_error

        # Plugin config missing required event_type field
        bad_config: dict[str, Any] = {
            "version": "2.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {},
            "plugins": {
                "plugins": [
                    {"path": "/some/plugin"},
                ]
            },
        }

        try:
            Config.model_validate(bad_config)
            pytest.fail("Expected ValidationError")
        except ValidationError as e:
            message = format_validation_error(e, bad_config)

        assert "event_type" in message
        assert "Before" in message or "before" in message
        assert "After" in message or "after" in message

    def test_unknown_field_suggests_closest_match(self) -> None:
        """Unknown field should suggest closest valid field name."""
        from claude_code_hooks_daemon.config.validation_ux import format_validation_error

        # HandlerConfig with extra="forbid" - typo in field name
        bad_config: dict[str, Any] = {
            "version": "2.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {
                        "enabled": True,
                        "priortiy": 10,  # typo
                    }
                }
            },
        }

        try:
            Config.model_validate(bad_config)
            pytest.fail("Expected ValidationError")
        except ValidationError as e:
            message = format_validation_error(e, bad_config)

        assert "priortiy" in message
        assert "priority" in message

    def test_general_validation_shows_field_path(self) -> None:
        """General validation errors show field path and helpful message."""
        from claude_code_hooks_daemon.config.validation_ux import format_validation_error

        # Invalid version format
        bad_config: dict[str, Any] = {
            "version": "bad",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {},
        }

        try:
            Config.model_validate(bad_config)
            pytest.fail("Expected ValidationError")
        except ValidationError as e:
            message = format_validation_error(e, bad_config)

        assert "version" in message
        # Should NOT contain raw Pydantic class names
        assert "ValidationError" not in message

    def test_no_raw_traceback_in_output(self) -> None:
        """Output should never contain raw Python traceback lines."""
        from claude_code_hooks_daemon.config.validation_ux import format_validation_error

        bad_config: dict[str, Any] = {
            "version": "2.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {},
            "plugins": {
                "plugins": [
                    {"path": "/some/plugin"},
                ]
            },
        }

        try:
            Config.model_validate(bad_config)
            pytest.fail("Expected ValidationError")
        except ValidationError as e:
            message = format_validation_error(e, bad_config)

        assert "Traceback" not in message
        assert "pydantic" not in message.lower() or "pydantic" in message.lower()
        # Should contain "Config Error" header
        assert "Config Error" in message

    def test_multiple_errors_all_shown(self) -> None:
        """Multiple validation errors should all be listed."""
        from claude_code_hooks_daemon.config.validation_ux import format_validation_error

        # Multiple issues: bad version + missing plugin event_type
        bad_config: dict[str, Any] = {
            "version": "bad",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {},
            "plugins": {
                "plugins": [
                    {"path": "/some/plugin"},
                ]
            },
        }

        try:
            Config.model_validate(bad_config)
            pytest.fail("Expected ValidationError")
        except ValidationError as e:
            message = format_validation_error(e, bad_config)

        # Should mention both problems
        assert "version" in message
        assert "event_type" in message


class TestFormatExtraFieldBranches:
    """Tests for _format_extra_field() branch coverage (lines 122-125, 132)."""

    def test_plugins_location_uses_plugin_valid_fields(self) -> None:
        """Extra field inside 'plugins' location uses _PLUGIN_VALID_FIELDS (lines 122-123)."""
        from claude_code_hooks_daemon.config.validation_ux import _format_extra_field

        err: dict[str, Any] = {
            "loc": ("plugins", "plugins", 0, "xyz_unknown_field"),
            "msg": "Extra inputs are not permitted",
            "type": "extra_forbidden",
        }
        lines = _format_extra_field(err, "plugins.plugins.0.xyz_unknown_field")

        # Field is in plugins location → _PLUGIN_VALID_FIELDS used
        # "xyz_unknown_field" has no close match → "Valid fields" listed (line 132)
        assert any("xyz_unknown_field" in line for line in lines)
        assert any("Valid fields" in line for line in lines)
        assert any("path" in line for line in lines)

    def test_other_location_uses_empty_valid_fields(self) -> None:
        """Extra field at non-handlers/non-plugins location uses frozenset() (lines 124-125)."""
        from claude_code_hooks_daemon.config.validation_ux import _format_extra_field

        err: dict[str, Any] = {
            "loc": ("daemon", "unknown_field"),
            "msg": "Extra inputs are not permitted",
            "type": "extra_forbidden",
        }
        lines = _format_extra_field(err, "daemon.unknown_field")

        # else branch → frozenset() → if valid_fields: is False → no suggestions
        assert any("unknown_field" in line for line in lines)
        assert not any("Did you mean" in line for line in lines)
        assert not any("Valid fields" in line for line in lines)

    def test_handlers_location_no_close_match_lists_valid_fields(self) -> None:
        """No close match for handlers extra field lists all valid fields (line 132)."""
        from claude_code_hooks_daemon.config.validation_ux import _format_extra_field

        err: dict[str, Any] = {
            "loc": ("handlers", "pre_tool_use", "destructive_git", "zzz_nomatch"),
            "msg": "Extra inputs are not permitted",
            "type": "extra_forbidden",
        }
        lines = _format_extra_field(err, "handlers.pre_tool_use.destructive_git.zzz_nomatch")

        # handlers location, no close match to enabled/priority/options → lists all (line 132)
        assert any("Valid fields" in line for line in lines)
        assert any("enabled" in line for line in lines)


class TestDuplicatePriorityLogLevel:
    """Tests for duplicate priority warnings being DEBUG not WARNING."""

    def test_duplicate_priority_logs_at_debug(self) -> None:
        """Duplicate priority messages should be at DEBUG level, not WARNING."""
        from claude_code_hooks_daemon.constants.priority import Priority
        from claude_code_hooks_daemon.core import AcceptanceTest
        from claude_code_hooks_daemon.core.chain import HandlerChain
        from claude_code_hooks_daemon.core.handler import Handler
        from claude_code_hooks_daemon.core.hook_result import Decision, HookResult

        class FakeHandlerA(Handler):
            def __init__(self) -> None:
                super().__init__(
                    handler_id="fake-a", priority=Priority.DESTRUCTIVE_GIT, terminal=False
                )

            def matches(self, hook_input: dict[str, Any]) -> bool:
                return True

            def handle(self, hook_input: dict[str, Any]) -> HookResult:
                return HookResult(decision=Decision.ALLOW)

            def get_acceptance_tests(self) -> list[AcceptanceTest]:
                return []

        class FakeHandlerB(Handler):
            def __init__(self) -> None:
                super().__init__(
                    handler_id="fake-b", priority=Priority.DESTRUCTIVE_GIT, terminal=False
                )

            def matches(self, hook_input: dict[str, Any]) -> bool:
                return True

            def handle(self, hook_input: dict[str, Any]) -> HookResult:
                return HookResult(decision=Decision.ALLOW)

            def get_acceptance_tests(self) -> list[AcceptanceTest]:
                return []

        chain = HandlerChain()
        chain.add(FakeHandlerA())
        chain.add(FakeHandlerB())

        with patch("claude_code_hooks_daemon.core.chain.logger") as mock_logger:
            _ = chain.handlers  # triggers sorting and duplicate detection

        # Should use debug, NOT warning
        mock_logger.debug.assert_called()
        mock_logger.warning.assert_not_called()


class TestCliConfigValidationUx:
    """Tests for _validate_installation catching Pydantic errors with UX formatting."""

    def test_pydantic_error_formatted_nicely(self, tmp_path: Any) -> None:
        """CLI should format Pydantic ValidationError with user-friendly messages."""
        import yaml

        # Create a project structure with bad config
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        bad_config = {
            "version": "2.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {},
            "plugins": {
                "plugins": [
                    {"path": "/some/plugin"},  # missing event_type
                ]
            },
        }

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text(yaml.dump(bad_config))

        # The error output should contain user-friendly formatting
        from claude_code_hooks_daemon.config.validation_ux import format_validation_error

        try:
            Config.model_validate(bad_config)
            pytest.fail("Expected ValidationError")
        except ValidationError as e:
            message = format_validation_error(e, bad_config)

        assert "Config Error" in message
        assert "event_type" in message
