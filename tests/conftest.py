"""Pytest configuration and shared fixtures for hooks daemon tests.

This module provides test fixtures and utilities used across all test files.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.core.response_schemas import (
    get_response_schema,
    is_valid_response,
    validate_response,
)


@pytest.fixture
def response_validator():
    """Fixture providing response validation utilities.

    Usage:
        def test_handler_response(response_validator):
            response = {"hookSpecificOutput": {...}}
            response_validator.assert_valid("PreToolUse", response)
    """

    class ResponseValidator:
        """Helper class for validating hook responses in tests."""

        @staticmethod
        def assert_valid(event_name: str, response: dict[str, Any]) -> None:
            """Assert that a response is valid for the given event.

            Args:
                event_name: Hook event name
                response: Response dictionary to validate

            Raises:
                AssertionError: If response is invalid
            """
            errors = validate_response(event_name, response)
            if errors:
                error_msg = f"Invalid {event_name} response:\n" + "\n".join(
                    f"  - {err}" for err in errors
                )
                raise AssertionError(error_msg)

        @staticmethod
        def assert_invalid(event_name: str, response: dict[str, Any]) -> None:
            """Assert that a response is INVALID for the given event.

            Useful for testing that validation catches bad responses.

            Args:
                event_name: Hook event name
                response: Response dictionary to validate

            Raises:
                AssertionError: If response is unexpectedly valid
            """
            if is_valid_response(event_name, response):
                raise AssertionError(
                    f"Expected invalid {event_name} response, but validation passed"
                )

        @staticmethod
        def get_errors(event_name: str, response: dict[str, Any]) -> list[str]:
            """Get validation errors for a response.

            Args:
                event_name: Hook event name
                response: Response dictionary to validate

            Returns:
                List of validation error messages
            """
            return validate_response(event_name, response)

        @staticmethod
        def get_schema(event_name: str) -> dict[str, Any]:
            """Get the JSON schema for an event.

            Args:
                event_name: Hook event name

            Returns:
                JSON schema dictionary
            """
            return get_response_schema(event_name)

    return ResponseValidator()


@pytest.fixture
def hook_result_validator(response_validator):
    """Fixture for validating HookResult.to_json() output.

    Usage:
        def test_hook_result(hook_result_validator):
            result = HookResult(decision=Decision.DENY, reason="Test")
            hook_result_validator.assert_valid("PreToolUse", result)
    """

    class HookResultValidator:
        """Helper class for validating HookResult instances."""

        def __init__(self, response_validator):
            self.response_validator = response_validator

        def assert_valid(self, event_name: str, hook_result) -> None:
            """Assert that a HookResult produces valid JSON for the event.

            Args:
                event_name: Hook event name
                hook_result: HookResult instance

            Raises:
                AssertionError: If response is invalid
            """
            response = hook_result.to_json(event_name)
            self.response_validator.assert_valid(event_name, response)

        def get_errors(self, event_name: str, hook_result) -> list[str]:
            """Get validation errors for a HookResult's JSON output.

            Args:
                event_name: Hook event name
                hook_result: HookResult instance

            Returns:
                List of validation error messages
            """
            response = hook_result.to_json(event_name)
            return self.response_validator.get_errors(event_name, response)

    return HookResultValidator(response_validator)
