"""Tests for input schema validation.

Tests validation of hook_input structures from Claude Code,
ensuring we catch malformed events and wrong field names.
"""

from claude_code_hooks_daemon.core.input_schemas import (
    INPUT_SCHEMAS,
    get_input_schema,
    is_valid_input,
    validate_input,
)


class TestSchemaRegistry:
    """Test schema registry and retrieval."""

    def test_all_event_types_have_schemas(self):
        """All known event types have input schemas."""
        expected_events = [
            "PreToolUse",
            "PostToolUse",
            "PermissionRequest",
            "Notification",
            "SessionStart",
            "SessionEnd",
            "PreCompact",
            "UserPromptSubmit",
            "Stop",
            "SubagentStop",
        ]

        for event_name in expected_events:
            assert event_name in INPUT_SCHEMAS, f"Missing schema for {event_name}"

    def test_get_input_schema_returns_schema(self):
        """get_input_schema returns schema for known events."""
        schema = get_input_schema("PreToolUse")
        assert schema is not None
        assert "type" in schema
        assert schema["type"] == "object"

    def test_get_input_schema_returns_none_for_unknown(self):
        """get_input_schema returns None for unknown events."""
        schema = get_input_schema("UnknownEvent")
        assert schema is None


class TestPreToolUseValidation:
    """Test PreToolUse input validation."""

    def test_real_claude_code_data_from_official_docs(self):
        """CRITICAL: Test with REAL Claude Code data structure from official docs.

        Reference: https://code.claude.com/docs/en/hooks (PreToolUse Input section)

        Claude Code sends: {hook_event_name, tool_name, tool_input, session_id, etc.}
        This structure is documented and confirmed in the official hooks reference.
        """
        # This is EXACTLY what Claude Code sends per official docs
        hook_input = {
            "session_id": "test-123",
            "transcript_path": "/test/path.jsonl",
            "cwd": "/workspace",
            "permission_mode": "default",
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "/root/.claude/plans/test.md", "content": "test content"},
            "tool_use_id": "test-id",
        }

        # This MUST pass - it's real Claude Code data!
        errors = validate_input("PreToolUse", hook_input)
        assert errors == [], f"Real Claude Code data rejected! Errors: {errors}"
        assert is_valid_input("PreToolUse", hook_input)

    def test_valid_pre_tool_use_bash(self):
        """Valid PreToolUse Bash event passes validation."""
        hook_input = {
            "session_id": "test-session-123",
            "transcript_path": "/path/to/transcript.jsonl",
            "cwd": "/workspace",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
            "tool_use_id": "tool_123",
        }

        errors = validate_input("PreToolUse", hook_input)
        assert errors == []
        assert is_valid_input("PreToolUse", hook_input)

    def test_valid_pre_tool_use_minimal(self):
        """Minimal valid PreToolUse event passes validation."""
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
        }

        errors = validate_input("PreToolUse", hook_input)
        assert errors == []

    def test_missing_tool_name(self):
        """Missing tool_name field fails validation."""
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_input": {"command": "ls"},
        }

        errors = validate_input("PreToolUse", hook_input)
        assert len(errors) > 0
        assert any("tool_name" in error for error in errors)

    def test_missing_hook_event_name(self):
        """Missing hook_event_name field fails validation."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }

        errors = validate_input("PreToolUse", hook_input)
        assert len(errors) > 0
        assert any("hook_event_name" in error for error in errors)


class TestPostToolUseValidation:
    """Test PostToolUse input validation - CRITICAL for catching tool_output bug."""

    def test_valid_post_tool_use_bash(self):
        """Valid PostToolUse Bash event with tool_response passes validation."""
        hook_input = {
            "session_id": "test-session-123",
            "transcript_path": "/path/to/transcript.jsonl",
            "cwd": "/workspace",
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
            "tool_response": {
                "stdout": "file1.txt\nfile2.txt",
                "stderr": "",
                "interrupted": False,
                "isImage": False,
            },
            "tool_use_id": "tool_123",
        }

        errors = validate_input("PostToolUse", hook_input)
        assert errors == []
        assert is_valid_input("PostToolUse", hook_input)

    def test_missing_tool_response(self):
        """Missing tool_response field fails validation."""
        hook_input = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }

        errors = validate_input("PostToolUse", hook_input)
        assert len(errors) > 0
        assert any("tool_response" in error for error in errors)

    def test_wrong_field_tool_output_instead_of_response(self):
        """Using tool_output instead of tool_response fails validation.

        This is the CRITICAL bug we're catching - handlers were using
        tool_output which doesn't exist in real events.
        """
        hook_input = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_output": {  # WRONG FIELD NAME!
                "exit_code": 0,
                "stdout": "output",
                "stderr": "",
            },
        }

        errors = validate_input("PostToolUse", hook_input)
        assert len(errors) > 0
        # Should fail because tool_response is required and tool_output is present
        assert not is_valid_input("PostToolUse", hook_input)

    def test_valid_post_tool_use_read(self):
        """Valid PostToolUse Read event with file structure."""
        hook_input = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/test.py"},
            "tool_response": {
                "type": "text",
                "file": {
                    "filePath": "/workspace/test.py",
                    "content": "print('hello')",
                    "numLines": 1,
                    "startLine": 1,
                    "totalLines": 1,
                },
            },
        }

        errors = validate_input("PostToolUse", hook_input)
        assert errors == []

    def test_valid_post_tool_use_glob(self):
        """Valid PostToolUse Glob event with filenames array."""
        hook_input = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Glob",
            "tool_input": {"pattern": "**/*.py"},
            "tool_response": {
                "filenames": ["/workspace/test.py", "/workspace/src/main.py"],
                "durationMs": 38,
                "numFiles": 2,
                "truncated": False,
            },
        }

        errors = validate_input("PostToolUse", hook_input)
        assert errors == []


class TestPermissionRequestValidation:
    """Test PermissionRequest input validation - catches permission_type bug."""

    def test_valid_permission_request(self):
        """Valid PermissionRequest with permission_suggestions passes."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
            "permission_suggestions": [{"prompt": "Allow dangerous command?", "default": "deny"}],
        }

        errors = validate_input("PermissionRequest", hook_input)
        assert errors == []

    def test_missing_permission_suggestions(self):
        """Missing permission_suggestions fails validation."""
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
        }

        errors = validate_input("PermissionRequest", hook_input)
        assert len(errors) > 0
        assert any("permission_suggestions" in error for error in errors)

    def test_wrong_field_permission_type_instead_of_suggestions(self):
        """Using permission_type instead of permission_suggestions fails.

        This is the bug in AutoApproveReadsHandler.
        """
        hook_input = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/test.py"},
            "permission_type": "read",  # WRONG FIELD!
            "resource": "test.py",  # WRONG FIELD!
        }

        errors = validate_input("PermissionRequest", hook_input)
        assert len(errors) > 0
        assert not is_valid_input("PermissionRequest", hook_input)


class TestNotificationValidation:
    """Test Notification input validation - catches severity bug."""

    def test_valid_notification(self):
        """Valid Notification with notification_type passes."""
        hook_input = {
            "hook_event_name": "Notification",
            "notification_type": "permission_prompt",
            "message": "Permission required",
        }

        errors = validate_input("Notification", hook_input)
        assert errors == []

    def test_valid_notification_types(self):
        """All documented notification types are valid."""
        valid_types = ["permission_prompt", "idle_prompt", "auth_success"]

        for notif_type in valid_types:
            hook_input = {
                "hook_event_name": "Notification",
                "notification_type": notif_type,
            }
            errors = validate_input("Notification", hook_input)
            assert errors == [], f"Type {notif_type} should be valid"

    def test_missing_notification_type(self):
        """Missing notification_type fails validation."""
        hook_input = {
            "hook_event_name": "Notification",
            "message": "Test message",
        }

        errors = validate_input("Notification", hook_input)
        assert len(errors) > 0
        assert any("notification_type" in error for error in errors)

    def test_wrong_field_severity_instead_of_notification_type(self):
        """Using severity instead of notification_type fails.

        This was the bug in NotificationLoggerHandler tests.
        """
        hook_input = {
            "hook_event_name": "Notification",
            "severity": "warning",  # WRONG FIELD!
            "message": "Test message",
        }

        errors = validate_input("Notification", hook_input)
        assert len(errors) > 0
        # Should fail because notification_type is required
        assert not is_valid_input("Notification", hook_input)


class TestSessionStartValidation:
    """Test SessionStart input validation."""

    def test_valid_session_start(self):
        """Valid SessionStart event passes."""
        hook_input = {
            "hook_event_name": "SessionStart",
            "session_id": "test-session-123",
            "transcript_path": "/path/to/transcript.jsonl",
        }

        errors = validate_input("SessionStart", hook_input)
        assert errors == []

    def test_missing_session_id(self):
        """Missing session_id fails validation."""
        hook_input = {
            "hook_event_name": "SessionStart",
        }

        errors = validate_input("SessionStart", hook_input)
        assert len(errors) > 0
        assert any("session_id" in error for error in errors)


class TestUserPromptSubmitValidation:
    """Test UserPromptSubmit input validation."""

    def test_valid_user_prompt_submit(self):
        """Valid UserPromptSubmit event passes."""
        hook_input = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "continue",
            "transcript_path": "/path/to/transcript.jsonl",
        }

        errors = validate_input("UserPromptSubmit", hook_input)
        assert errors == []

    def test_missing_prompt(self):
        """Missing prompt fails validation."""
        hook_input = {
            "hook_event_name": "UserPromptSubmit",
        }

        errors = validate_input("UserPromptSubmit", hook_input)
        assert len(errors) > 0
        assert any("prompt" in error for error in errors)


class TestSubagentStopValidation:
    """Test SubagentStop input validation."""

    def test_valid_subagent_stop(self):
        """Valid SubagentStop event passes."""
        hook_input = {
            "hook_event_name": "SubagentStop",
            "subagent_id": "agent-123",
            "subagent_type": "python-developer",
        }

        errors = validate_input("SubagentStop", hook_input)
        assert errors == []

    def test_minimal_subagent_stop(self):
        """Minimal SubagentStop event passes (fields optional)."""
        hook_input = {
            "hook_event_name": "SubagentStop",
        }

        errors = validate_input("SubagentStop", hook_input)
        assert errors == []


class TestUnknownEventType:
    """Test behavior with unknown event types."""

    def test_validate_unknown_event_returns_empty_list(self):
        """Validating unknown event type returns empty errors (fail-open)."""
        hook_input = {"foo": "bar"}

        errors = validate_input("UnknownEvent", hook_input)
        assert errors == []  # Fail-open for unknown events

    def test_is_valid_unknown_event_returns_true(self):
        """Unknown event types are considered valid (fail-open)."""
        hook_input = {"foo": "bar"}

        assert is_valid_input("UnknownEvent", hook_input)


class TestForwardCompatibility:
    """Test that schemas allow additional properties for forward compatibility."""

    def test_additional_properties_allowed_pre_tool_use(self):
        """Additional unknown properties are allowed in PreToolUse."""
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "future_field": "future_value",  # Unknown field
            "another_new_field": {"nested": "data"},
        }

        errors = validate_input("PreToolUse", hook_input)
        assert errors == []  # Should not fail on unknown fields

    def test_additional_properties_allowed_post_tool_use(self):
        """Additional unknown properties are allowed in PostToolUse."""
        hook_input = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_response": {"stdout": "", "stderr": ""},
            "future_metadata": {"version": "2.0"},
        }

        errors = validate_input("PostToolUse", hook_input)
        assert errors == []


class TestValidationPerformance:
    """Test validation performance meets targets."""

    def test_validation_completes_quickly(self):
        """Validation completes under 5ms (target from research)."""
        import time

        hook_input = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_response": {
                "stdout": "output",
                "stderr": "",
                "interrupted": False,
                "isImage": False,
            },
        }

        start = time.perf_counter()
        for _ in range(1000):
            validate_input("PostToolUse", hook_input)
        elapsed = (time.perf_counter() - start) * 1000  # ms

        per_validation = elapsed / 1000
        assert per_validation < 5.0, f"Validation took {per_validation}ms (target: <5ms)"
