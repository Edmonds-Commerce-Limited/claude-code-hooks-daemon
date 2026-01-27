"""Tests for hook response JSON schemas.

These tests verify that:
1. Response schemas are correctly defined
2. Valid responses pass validation
3. Invalid responses fail validation
4. All hook events have schemas
"""

import pytest

from claude_code_hooks_daemon.core.response_schemas import (
    RESPONSE_SCHEMAS,
    get_response_schema,
    is_valid_response,
    validate_response,
)


class TestSchemaRegistry:
    """Tests for the schema registry."""

    def test_all_events_have_schemas(self):
        """All known hook events should have schemas."""
        expected_events = [
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
        ]

        for event in expected_events:
            assert event in RESPONSE_SCHEMAS, f"Missing schema for {event}"

    def test_get_response_schema_valid_event(self):
        """get_response_schema should return schema for valid events."""
        schema = get_response_schema("PreToolUse")
        assert isinstance(schema, dict)
        assert "type" in schema
        assert schema["type"] == "object"

    def test_get_response_schema_invalid_event(self):
        """get_response_schema should raise ValueError for unknown events."""
        with pytest.raises(ValueError, match="Unknown hook event"):
            get_response_schema("InvalidEvent")


class TestPreToolUseSchema:
    """Tests for PreToolUse hook response schema."""

    def test_valid_minimal_response(self, response_validator):
        """Minimal valid response: empty (silent allow)."""
        response = {}
        response_validator.assert_valid("PreToolUse", response)

    def test_valid_allow_response(self, response_validator):
        """Valid allow response with context."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": "Some context",
            }
        }
        response_validator.assert_valid("PreToolUse", response)

    def test_valid_deny_response(self, response_validator):
        """Valid deny response with reason."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Destructive operation blocked",
                "additionalContext": "Run 'git status' first",
            }
        }
        response_validator.assert_valid("PreToolUse", response)

    def test_valid_ask_response(self, response_validator):
        """Valid ask response."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": "Needs user confirmation",
            }
        }
        response_validator.assert_valid("PreToolUse", response)

    def test_invalid_decision_value(self, response_validator):
        """Invalid permissionDecision value should fail."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "block",  # Wrong value
            }
        }
        response_validator.assert_invalid("PreToolUse", response)

    def test_invalid_wrong_event_name(self, response_validator):
        """Wrong hookEventName should fail."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",  # Wrong event
                "permissionDecision": "deny",
            }
        }
        response_validator.assert_invalid("PreToolUse", response)

    def test_invalid_extra_fields(self, response_validator):
        """Extra fields in hookSpecificOutput should fail."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "extraField": "not allowed",
            }
        }
        response_validator.assert_invalid("PreToolUse", response)

    def test_invalid_missing_hook_event_name(self, response_validator):
        """Missing hookEventName should fail."""
        response = {
            "hookSpecificOutput": {
                "permissionDecision": "deny",
            }
        }
        response_validator.assert_invalid("PreToolUse", response)


class TestPostToolUseSchema:
    """Tests for PostToolUse hook response schema."""

    def test_valid_minimal_response(self, response_validator):
        """Minimal valid response: empty."""
        response = {}
        response_validator.assert_valid("PostToolUse", response)

    def test_valid_allow_with_context(self, response_validator):
        """Valid allow response with context."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "Tool executed successfully",
            }
        }
        response_validator.assert_valid("PostToolUse", response)

    def test_valid_block_response(self, response_validator):
        """Valid block response."""
        response = {
            "decision": "block",
            "reason": "Output validation failed",
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "Check the error logs",
            },
        }
        response_validator.assert_valid("PostToolUse", response)

    def test_invalid_decision_in_hook_output(self, response_validator):
        """Decision should be top-level, not in hookSpecificOutput."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "permissionDecision": "deny",  # Wrong location
            }
        }
        response_validator.assert_invalid("PostToolUse", response)

    def test_invalid_decision_value(self, response_validator):
        """Only 'block' is valid for decision field."""
        response = {
            "decision": "deny",  # Wrong value (only "block" allowed)
            "reason": "Test",
        }
        response_validator.assert_invalid("PostToolUse", response)


class TestStopSchema:
    """Tests for Stop hook response schema."""

    def test_valid_minimal_response(self, response_validator):
        """Minimal valid response: empty."""
        response = {}
        response_validator.assert_valid("Stop", response)

    def test_valid_block_response(self, response_validator):
        """Valid block response."""
        response = {
            "decision": "block",
            "reason": "Cannot stop during critical operation",
        }
        response_validator.assert_valid("Stop", response)

    def test_invalid_hook_specific_output(self, response_validator):
        """Stop hook should NOT use hookSpecificOutput."""
        response = {
            "decision": "block",
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": "Not allowed",
            },
        }
        response_validator.assert_invalid("Stop", response)


class TestSubagentStopSchema:
    """Tests for SubagentStop hook response schema (identical to Stop)."""

    def test_valid_minimal_response(self, response_validator):
        """Minimal valid response: empty."""
        response = {}
        response_validator.assert_valid("SubagentStop", response)

    def test_valid_block_response(self, response_validator):
        """Valid block response."""
        response = {
            "decision": "block",
            "reason": "Subagent must complete task",
        }
        response_validator.assert_valid("SubagentStop", response)


class TestPermissionRequestSchema:
    """Tests for PermissionRequest hook response schema."""

    def test_valid_minimal_response(self, response_validator):
        """Minimal valid response: empty."""
        response = {}
        response_validator.assert_valid("PermissionRequest", response)

    def test_valid_allow_response(self, response_validator):
        """Valid allow response."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "behavior": "allow",
                },
            }
        }
        response_validator.assert_valid("PermissionRequest", response)

    def test_valid_deny_with_updated_input(self, response_validator):
        """Valid deny response with updated input."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "behavior": "deny",
                    "updatedInput": {
                        "command": "safer-command",
                    },
                },
                "additionalContext": "Modified command for safety",
            }
        }
        response_validator.assert_valid("PermissionRequest", response)

    def test_invalid_flat_decision(self, response_validator):
        """Decision must be nested with behavior field."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "permissionDecision": "deny",  # Wrong structure
            }
        }
        response_validator.assert_invalid("PermissionRequest", response)

    def test_invalid_missing_behavior(self, response_validator):
        """Decision object must have behavior field."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "updatedInput": {},  # Missing behavior
                },
            }
        }
        response_validator.assert_invalid("PermissionRequest", response)


class TestSessionStartSchema:
    """Tests for SessionStart hook response schema."""

    def test_valid_minimal_response(self, response_validator):
        """Minimal valid response: empty."""
        response = {}
        response_validator.assert_valid("SessionStart", response)

    def test_valid_with_context(self, response_validator):
        """Valid response with additional context."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "Session initialized with custom settings",
            }
        }
        response_validator.assert_valid("SessionStart", response)

    def test_invalid_with_decision(self, response_validator):
        """SessionStart should NOT have decision fields."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "permissionDecision": "allow",  # Not allowed
            }
        }
        response_validator.assert_invalid("SessionStart", response)


class TestSessionEndSchema:
    """Tests for SessionEnd hook response schema."""

    def test_valid_minimal_response(self, response_validator):
        """Minimal valid response: empty."""
        response = {}
        response_validator.assert_valid("SessionEnd", response)

    def test_valid_with_context(self, response_validator):
        """Valid response with context."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "SessionEnd",
                "additionalContext": "Session cleanup complete",
            }
        }
        response_validator.assert_valid("SessionEnd", response)


class TestPreCompactSchema:
    """Tests for PreCompact hook response schema."""

    def test_valid_minimal_response(self, response_validator):
        """Minimal valid response: empty."""
        response = {}
        response_validator.assert_valid("PreCompact", response)

    def test_valid_with_context(self, response_validator):
        """Valid response with context."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PreCompact",
                "additionalContext": "✅ PreCompact hook system active",
            }
        }
        response_validator.assert_valid("PreCompact", response)


class TestUserPromptSubmitSchema:
    """Tests for UserPromptSubmit hook response schema."""

    def test_valid_minimal_response(self, response_validator):
        """Minimal valid response: empty."""
        response = {}
        response_validator.assert_valid("UserPromptSubmit", response)

    def test_valid_with_context(self, response_validator):
        """Valid response with context."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "Auto-continue triggered",
            }
        }
        response_validator.assert_valid("UserPromptSubmit", response)


class TestNotificationSchema:
    """Tests for Notification hook response schema."""

    def test_valid_minimal_response(self, response_validator):
        """Minimal valid response: empty."""
        response = {}
        response_validator.assert_valid("Notification", response)

    def test_valid_with_context(self, response_validator):
        """Valid response with context."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "Notification",
                "additionalContext": "Notification logged",
            }
        }
        response_validator.assert_valid("Notification", response)


class TestValidationHelpers:
    """Tests for validation helper functions."""

    def test_is_valid_response_true(self):
        """is_valid_response should return True for valid responses."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
            }
        }
        assert is_valid_response("PreToolUse", response) is True

    def test_is_valid_response_false(self):
        """is_valid_response should return False for invalid responses."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "invalid",
            }
        }
        assert is_valid_response("PreToolUse", response) is False

    def test_validate_response_returns_errors(self):
        """validate_response should return list of error messages."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "invalid",
            }
        }
        errors = validate_response("PreToolUse", response)
        assert len(errors) > 0
        assert isinstance(errors[0], str)

    def test_validate_response_empty_on_valid(self):
        """validate_response should return empty list for valid responses."""
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
            }
        }
        errors = validate_response("PreToolUse", response)
        assert len(errors) == 0

    def test_validate_response_without_jsonschema(self, monkeypatch):
        """validate_response should handle missing jsonschema gracefully."""
        import builtins
        import sys

        # Mock the import to raise ImportError
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "jsonschema":
                raise ImportError("jsonschema not installed")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        # Clear any cached imports
        if "jsonschema" in sys.modules:
            monkeypatch.delitem(sys.modules, "jsonschema")

        response = {"hookSpecificOutput": {"hookEventName": "PreToolUse"}}
        errors = validate_response("PreToolUse", response)

        assert len(errors) == 1
        assert "jsonschema not installed" in errors[0]
