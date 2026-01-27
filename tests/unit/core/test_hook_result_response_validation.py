"""Tests validating HookResult.to_json() produces valid responses for each event type.

EXPECTED: Many of these tests will FAIL, exposing the response formatting bug.

The current HookResult.to_json() implementation returns ONE format for all events,
but different events require different response structures according to Claude Code's API.
"""

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision, HookResult


class TestPreToolUseResponses:
    """Test HookResult produces valid PreToolUse responses."""

    def test_silent_allow(self, hook_result_validator):
        """Silent allow (empty response) should be valid."""
        result = HookResult(decision=Decision.ALLOW)
        hook_result_validator.assert_valid("PreToolUse", result)

    def test_allow_with_context(self, hook_result_validator):
        """Allow with context should be valid."""
        result = HookResult(
            decision=Decision.ALLOW,
            context=["Everything looks good", "Proceeding with operation"],
        )
        hook_result_validator.assert_valid("PreToolUse", result)

    def test_deny_with_reason(self, hook_result_validator):
        """Deny decision should include permissionDecision."""
        result = HookResult(
            decision=Decision.DENY,
            reason="Destructive operation blocked",
            context=["Run 'git status' first"],
        )
        hook_result_validator.assert_valid("PreToolUse", result)

    def test_ask_with_reason(self, hook_result_validator):
        """Ask decision should include permissionDecision."""
        result = HookResult(
            decision=Decision.ASK,
            reason="Needs user confirmation",
        )
        hook_result_validator.assert_valid("PreToolUse", result)

    def test_error_response(self, hook_result_validator):
        """Error responses should be valid."""
        result = HookResult.error(
            error_type="config_error",
            error_details="Invalid configuration",
        )
        hook_result_validator.assert_valid("PreToolUse", result)


class TestPostToolUseResponses:
    """Test HookResult produces valid PostToolUse responses.

    EXPECTED TO FAIL: PostToolUse requires top-level 'decision' field,
    not 'permissionDecision' inside hookSpecificOutput.
    """

    def test_silent_allow(self, hook_result_validator):
        """Silent allow (empty response) should be valid."""
        result = HookResult(decision=Decision.ALLOW)
        hook_result_validator.assert_valid("PostToolUse", result)

    def test_allow_with_context(self, hook_result_validator):
        """Allow with context should be valid."""
        result = HookResult(
            decision=Decision.ALLOW,
            context=["Tool executed successfully"],
        )
        hook_result_validator.assert_valid("PostToolUse", result)

    def test_block_response(self, hook_result_validator):
        """EXPECTED TO FAIL: Block response needs top-level 'decision: block'."""
        result = HookResult(
            decision=Decision.DENY,  # Maps to "block" in PostToolUse
            reason="Output validation failed",
            context=["Check the error logs"],
        )
        # This will likely fail because current implementation uses
        # permissionDecision instead of top-level decision
        hook_result_validator.assert_valid("PostToolUse", result)

    def test_error_response(self, hook_result_validator):
        """Error responses should be valid."""
        result = HookResult.error(
            error_type="validation_error",
            error_details="Output validation failed",
        )
        hook_result_validator.assert_valid("PostToolUse", result)


class TestStopResponses:
    """Test HookResult produces valid Stop responses.

    EXPECTED TO FAIL: Stop requires top-level 'decision' field,
    NO hookSpecificOutput structure.
    """

    def test_silent_allow(self, hook_result_validator):
        """Silent allow (empty response) should be valid."""
        result = HookResult(decision=Decision.ALLOW)
        hook_result_validator.assert_valid("Stop", result)

    def test_block_response(self, hook_result_validator):
        """EXPECTED TO FAIL: Block needs top-level decision, no hookSpecificOutput."""
        result = HookResult(
            decision=Decision.DENY,
            reason="Cannot stop during critical operation",
        )
        # This will likely fail because current implementation wraps
        # everything in hookSpecificOutput
        hook_result_validator.assert_valid("Stop", result)

    def test_error_response(self, hook_result_validator):
        """Error responses should be valid."""
        result = HookResult.error(
            error_type="stop_error",
            error_details="Stop hook failed",
        )
        hook_result_validator.assert_valid("Stop", result)


class TestSubagentStopResponses:
    """Test HookResult produces valid SubagentStop responses.

    EXPECTED TO FAIL: SubagentStop has same structure as Stop.
    """

    def test_silent_allow(self, hook_result_validator):
        """Silent allow (empty response) should be valid."""
        result = HookResult(decision=Decision.ALLOW)
        hook_result_validator.assert_valid("SubagentStop", result)

    def test_block_response(self, hook_result_validator):
        """EXPECTED TO FAIL: Block needs top-level decision, no hookSpecificOutput."""
        result = HookResult(
            decision=Decision.DENY,
            reason="Subagent must complete task",
        )
        hook_result_validator.assert_valid("SubagentStop", result)

    def test_allow_with_context(self, hook_result_validator):
        """EXPECTED TO FAIL: Context might be wrapped incorrectly."""
        result = HookResult(
            decision=Decision.ALLOW,
            context=["Subagent task completed"],
        )
        # This might fail if context is put in hookSpecificOutput
        # when it should be at top level (or not present for Stop events)
        hook_result_validator.assert_valid("SubagentStop", result)


class TestPermissionRequestResponses:
    """Test HookResult produces valid PermissionRequest responses.

    EXPECTED TO FAIL: PermissionRequest requires nested 'decision.behavior' structure.
    """

    def test_silent_allow(self, hook_result_validator):
        """Silent allow (empty response) should be valid."""
        result = HookResult(decision=Decision.ALLOW)
        hook_result_validator.assert_valid("PermissionRequest", result)

    def test_allow_response(self, hook_result_validator):
        """EXPECTED TO FAIL: Allow needs 'decision: {behavior: allow}' structure."""
        result = HookResult(
            decision=Decision.ALLOW,
            context=["Permission granted"],
        )
        # This will likely fail because current implementation uses
        # permissionDecision instead of decision.behavior
        hook_result_validator.assert_valid("PermissionRequest", result)

    def test_deny_response(self, hook_result_validator):
        """EXPECTED TO FAIL: Deny needs 'decision: {behavior: deny}' structure."""
        result = HookResult(
            decision=Decision.DENY,
            reason="Permission denied",
        )
        hook_result_validator.assert_valid("PermissionRequest", result)


class TestSessionStartResponses:
    """Test HookResult produces valid SessionStart responses.

    EXPECTED TO FAIL: SessionStart should NOT include permissionDecision fields.
    """

    def test_silent_allow(self, hook_result_validator):
        """Silent allow (empty response) should be valid."""
        result = HookResult(decision=Decision.ALLOW)
        hook_result_validator.assert_valid("SessionStart", result)

    def test_with_context(self, hook_result_validator):
        """Context-only response should be valid."""
        result = HookResult(
            decision=Decision.ALLOW,
            context=["Session initialized with custom settings"],
        )
        hook_result_validator.assert_valid("SessionStart", result)

    def test_deny_response_invalid(self, hook_result_validator):
        """EXPECTED TO FAIL: SessionStart should NOT support deny decisions."""
        result = HookResult(
            decision=Decision.DENY,
            reason="Cannot start session",
        )
        # This should fail because SessionStart doesn't support permissionDecision
        errors = hook_result_validator.get_errors("SessionStart", result)
        assert len(errors) > 0, "SessionStart should not accept deny decisions"


class TestSessionEndResponses:
    """Test HookResult produces valid SessionEnd responses."""

    def test_silent_allow(self, hook_result_validator):
        """Silent allow (empty response) should be valid."""
        result = HookResult(decision=Decision.ALLOW)
        hook_result_validator.assert_valid("SessionEnd", result)

    def test_with_context(self, hook_result_validator):
        """Context-only response should be valid."""
        result = HookResult(
            decision=Decision.ALLOW,
            context=["Session cleanup complete"],
        )
        hook_result_validator.assert_valid("SessionEnd", result)


class TestPreCompactResponses:
    """Test HookResult produces valid PreCompact responses."""

    def test_silent_allow(self, hook_result_validator):
        """Silent allow (empty response) should be valid."""
        result = HookResult(decision=Decision.ALLOW)
        hook_result_validator.assert_valid("PreCompact", result)

    def test_with_context(self, hook_result_validator):
        """Context-only response should be valid."""
        result = HookResult(
            decision=Decision.ALLOW,
            context=["✅ PreCompact hook system active"],
        )
        hook_result_validator.assert_valid("PreCompact", result)


class TestUserPromptSubmitResponses:
    """Test HookResult produces valid UserPromptSubmit responses."""

    def test_silent_allow(self, hook_result_validator):
        """Silent allow (empty response) should be valid."""
        result = HookResult(decision=Decision.ALLOW)
        hook_result_validator.assert_valid("UserPromptSubmit", result)

    def test_with_context(self, hook_result_validator):
        """Context-only response should be valid."""
        result = HookResult(
            decision=Decision.ALLOW,
            context=["Auto-continue triggered"],
        )
        hook_result_validator.assert_valid("UserPromptSubmit", result)


class TestNotificationResponses:
    """Test HookResult produces valid Notification responses."""

    def test_silent_allow(self, hook_result_validator):
        """Silent allow (empty response) should be valid."""
        result = HookResult(decision=Decision.ALLOW)
        hook_result_validator.assert_valid("Notification", result)

    def test_with_context(self, hook_result_validator):
        """Context-only response should be valid."""
        result = HookResult(
            decision=Decision.ALLOW,
            context=["Notification logged"],
        )
        hook_result_validator.assert_valid("Notification", result)


class TestErrorResponsesAcrossEvents:
    """Test that error responses are valid for ALL event types.

    EXPECTED: These tests expose whether HookResult.error() produces
    event-appropriate responses.
    """

    @pytest.mark.parametrize(
        "event_name",
        [
            "PreToolUse",
            "PostToolUse",
            "Stop",
            "SubagentStop",
            "PermissionRequest",
            "SessionStart",
            "SessionEnd",
            "PreCompact",
            "UserPromptSubmit",
            "Notification",
        ],
    )
    def test_error_response_valid_for_event(self, hook_result_validator, event_name):
        """Error responses should be valid for each event type."""
        result = HookResult.error(
            error_type="test_error",
            error_details="Test error message",
        )
        # This will fail for events that don't support the current format
        hook_result_validator.assert_valid(event_name, result)
