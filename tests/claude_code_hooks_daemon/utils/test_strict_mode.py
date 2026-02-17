"""Tests for strict_mode error handling utilities.

Tests the DRY helper functions for three-tier error handling architecture.
"""

import logging

import pytest

from claude_code_hooks_daemon.utils.strict_mode import (
    crash_in_strict_mode,
    handle_tier2_error,
)


class TestHandleTier2Error:
    """Tests for handle_tier2_error() function."""

    def test_crashes_in_strict_mode(self) -> None:
        """TIER 2 errors should crash in strict_mode."""
        original_error = ImportError("jsonschema not installed")

        with pytest.raises(RuntimeError) as exc_info:
            handle_tier2_error(
                error=original_error,
                strict_mode=True,
                error_message="Input validation required in strict_mode",
            )

        # Should wrap the original error
        assert exc_info.value.__cause__ is original_error
        assert "Input validation required in strict_mode" in str(exc_info.value)

    def test_logs_warning_in_non_strict_mode(self, caplog: pytest.LogCaptureFixture) -> None:
        """TIER 2 errors should log warning in non-strict mode."""
        original_error = ImportError("jsonschema not installed")

        with caplog.at_level(logging.WARNING):
            handle_tier2_error(
                error=original_error,
                strict_mode=False,
                error_message="Input validation disabled",
            )

        # Should log warning and continue (not crash)
        assert "Input validation disabled" in caplog.text
        assert "jsonschema not installed" in caplog.text

    def test_uses_graceful_message_when_provided(self, caplog: pytest.LogCaptureFixture) -> None:
        """Should use graceful_message in non-strict mode if provided."""
        original_error = ImportError("module not found")

        with caplog.at_level(logging.WARNING):
            handle_tier2_error(
                error=original_error,
                strict_mode=False,
                error_message="Critical error in strict mode",
                graceful_message="Optional feature disabled",
            )

        # Should use graceful message, not error message
        assert "Optional feature disabled" in caplog.text
        assert "Critical error in strict mode" not in caplog.text

    def test_uses_error_message_when_graceful_message_not_provided(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should use error_message as fallback if graceful_message not provided."""
        original_error = ImportError("module not found")

        with caplog.at_level(logging.WARNING):
            handle_tier2_error(
                error=original_error,
                strict_mode=False,
                error_message="Feature disabled",
            )

        # Should use error message as fallback
        assert "Feature disabled" in caplog.text


class TestCrashInStrictMode:
    """Tests for crash_in_strict_mode() function."""

    def test_crashes_in_strict_mode(self) -> None:
        """Should crash with RuntimeError in strict_mode."""
        with pytest.raises(RuntimeError) as exc_info:
            crash_in_strict_mode(
                strict_mode=True,
                error_message="Handler discovery failed",
            )

        assert "Handler discovery failed" in str(exc_info.value)

    def test_returns_none_in_non_strict_mode(self) -> None:
        """Should return None in non-strict mode (no crash)."""
        result = crash_in_strict_mode(
            strict_mode=False,
            error_message="Handler discovery failed",
        )

        assert result is None

    def test_strict_mode_false_does_not_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """Should not log anything in non-strict mode (silent continue)."""
        with caplog.at_level(logging.DEBUG):
            crash_in_strict_mode(
                strict_mode=False,
                error_message="Some error",
            )

        # Should not log anything (caller handles logging if needed)
        assert "Some error" not in caplog.text
