"""Tests for HookEvent models and event handling."""

from typing import Any

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.constants import ToolName
from claude_code_hooks_daemon.core.event import EventType, HookEvent, HookInput, ToolInput


class TestEventType:
    """Tests for EventType enum."""

    def test_all_event_types_exist(self) -> None:
        """All expected event types should be defined."""
        expected_types = {
            "PreToolUse",
            "PostToolUse",
            "SessionStart",
            "SessionEnd",
            "PreCompact",
            "UserPromptSubmit",
            "PermissionRequest",
            "Notification",
            "Stop",
            "SubagentStop",
            "Status",  # STATUS_LINE event type
        }
        actual_types = {et.value for et in EventType}
        assert actual_types == expected_types

    def test_from_string_exact_match(self) -> None:
        """from_string should handle exact matches."""
        assert EventType.from_string("PreToolUse") == EventType.PRE_TOOL_USE
        assert EventType.from_string("PostToolUse") == EventType.POST_TOOL_USE
        assert EventType.from_string("Stop") == EventType.STOP

    def test_from_string_snake_case(self) -> None:
        """from_string should handle snake_case conversion."""
        assert EventType.from_string("pre_tool_use") == EventType.PRE_TOOL_USE
        assert EventType.from_string("post_tool_use") == EventType.POST_TOOL_USE
        assert EventType.from_string("session_start") == EventType.SESSION_START

    def test_from_string_case_insensitive(self) -> None:
        """from_string should be case insensitive."""
        assert EventType.from_string("PRETOOLUSE") == EventType.PRE_TOOL_USE
        assert EventType.from_string("pretooluse") == EventType.PRE_TOOL_USE
        assert EventType.from_string("PreToolUse") == EventType.PRE_TOOL_USE

    def test_from_string_invalid_type(self) -> None:
        """from_string should raise ValueError for unknown types."""
        with pytest.raises(ValueError, match="Unknown event type: InvalidType"):
            EventType.from_string("InvalidType")

    def test_from_string_error_message_lists_valid_types(self) -> None:
        """Error message should list all valid event types."""
        with pytest.raises(ValueError) as exc_info:
            EventType.from_string("BadEvent")

        error_msg = str(exc_info.value)
        assert "PreToolUse" in error_msg
        assert "Stop" in error_msg
        assert "Valid types:" in error_msg


class TestToolInput:
    """Tests for ToolInput model."""

    def test_empty_tool_input(self) -> None:
        """ToolInput should allow empty initialization."""
        tool_input = ToolInput()
        assert tool_input.command is None
        assert tool_input.file_path is None
        assert tool_input.pattern is None
        assert tool_input.content is None

    def test_bash_tool_input(self) -> None:
        """ToolInput should parse Bash tool data."""
        data = {"command": "git status"}
        tool_input = ToolInput.model_validate(data)
        assert tool_input.command == "git status"

    def test_write_tool_input(self) -> None:
        """ToolInput should parse Write tool data."""
        data = {"file_path": "/workspace/test.py", "content": "print('hello')"}
        tool_input = ToolInput.model_validate(data)
        assert tool_input.file_path == "/workspace/test.py"
        assert tool_input.content == "print('hello')"

    def test_edit_tool_input(self) -> None:
        """ToolInput should parse Edit tool data."""
        data = {
            "file_path": "/workspace/test.py",
            "old_string": "old",
            "new_string": "new",
        }
        tool_input = ToolInput.model_validate(data)
        assert tool_input.old_string == "old"
        assert tool_input.new_string == "new"

    def test_glob_tool_input(self) -> None:
        """ToolInput should parse Glob tool data."""
        data = {"pattern": "**/*.py"}
        tool_input = ToolInput.model_validate(data)
        assert tool_input.pattern == "**/*.py"

    def test_extra_fields_allowed(self) -> None:
        """ToolInput should allow extra fields."""
        data = {"command": "test", "custom_field": "custom_value"}
        tool_input = ToolInput.model_validate(data)
        assert tool_input.command == "test"

    def test_frozen_model(self) -> None:
        """ToolInput should be immutable."""
        tool_input = ToolInput(command="test")
        with pytest.raises(ValidationError):
            tool_input.command = "new_value"  # type: ignore[misc]


class TestHookInput:
    """Tests for HookInput model."""

    def test_empty_hook_input(self) -> None:
        """HookInput should allow empty initialization."""
        hook_input = HookInput()
        assert hook_input.tool_name is None
        assert hook_input.tool_input is None
        assert hook_input.session_id is None

    def test_pre_tool_use_input(self) -> None:
        """HookInput should parse PreToolUse data."""
        data = {
            "toolName": "Bash",
            "toolInput": {"command": "git status"},
            "sessionId": "session-123",
        }
        hook_input = HookInput.model_validate(data)
        assert hook_input.tool_name == ToolName.BASH
        assert hook_input.tool_input == {"command": "git status"}
        assert hook_input.session_id == "session-123"

    def test_field_aliases(self) -> None:
        """HookInput should support both camelCase and snake_case field names."""
        data = {
            "toolName": "Write",
            "toolInput": {"file_path": "test.py"},
            "sessionId": "session-123",
            "transcriptPath": "/path/to/transcript",
        }
        hook_input = HookInput.model_validate(data)
        assert hook_input.tool_name == ToolName.WRITE
        assert hook_input.session_id == "session-123"
        assert hook_input.transcript_path == "/path/to/transcript"

    def test_notification_event_input(self) -> None:
        """HookInput should parse Notification event data."""
        data = {"message": "Test notification"}
        hook_input = HookInput.model_validate(data)
        assert hook_input.message == "Test notification"

    def test_user_prompt_submit_input(self) -> None:
        """HookInput should parse UserPromptSubmit event data."""
        data = {"prompt": "Test prompt"}
        hook_input = HookInput.model_validate(data)
        assert hook_input.prompt == "Test prompt"

    def test_get_tool_input_model(self) -> None:
        """get_tool_input_model should return ToolInput instance."""
        data = {
            "toolName": "Bash",
            "toolInput": {"command": "git status"},
        }
        hook_input = HookInput.model_validate(data)
        tool_input = hook_input.get_tool_input_model()
        assert isinstance(tool_input, ToolInput)
        assert tool_input.command == "git status"

    def test_get_tool_input_model_none(self) -> None:
        """get_tool_input_model should return empty ToolInput when tool_input is None."""
        hook_input = HookInput()
        tool_input = hook_input.get_tool_input_model()
        assert isinstance(tool_input, ToolInput)
        assert tool_input.command is None

    def test_frozen_model(self) -> None:
        """HookInput should be immutable."""
        hook_input = HookInput(tool_name="Bash")
        with pytest.raises(ValidationError):
            hook_input.tool_name = "Write"  # type: ignore[misc]


class TestHookEvent:
    """Tests for HookEvent model."""

    def test_minimal_hook_event(self) -> None:
        """HookEvent should allow minimal initialization."""
        event = HookEvent(event_type=EventType.PRE_TOOL_USE)
        assert event.event_type == EventType.PRE_TOOL_USE
        assert isinstance(event.hook_input, HookInput)

    def test_full_hook_event(self) -> None:
        """HookEvent should parse complete event data."""
        data = {
            "event": "PreToolUse",
            "hook_input": {
                "toolName": "Bash",
                "toolInput": {"command": "git status"},
                "sessionId": "session-123",
            },
            "request_id": "req-456",
        }
        event = HookEvent.model_validate(data)
        assert event.event_type == EventType.PRE_TOOL_USE
        assert event.hook_input.tool_name == ToolName.BASH
        assert event.request_id == "req-456"

    def test_tool_name_property(self) -> None:
        """tool_name property should access hook_input.tool_name."""
        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(tool_name="Bash"),
        )
        assert event.tool_name == ToolName.BASH

    def test_tool_input_property(self) -> None:
        """tool_input property should access hook_input.tool_input."""
        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(tool_input={"command": "test"}),
        )
        assert event.tool_input == {"command": "test"}

    def test_session_id_property(self) -> None:
        """session_id property should access hook_input.session_id."""
        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(session_id="session-123"),
        )
        assert event.session_id == "session-123"

    def test_get_command(self) -> None:
        """get_command should extract command from Bash tool input."""
        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(
                tool_name="Bash",
                tool_input={"command": "git status"},
            ),
        )
        assert event.get_command() == "git status"

    def test_get_command_none(self) -> None:
        """get_command should return None when tool_input is None."""
        event = HookEvent(event_type=EventType.PRE_TOOL_USE)
        assert event.get_command() is None

    def test_get_file_path(self) -> None:
        """get_file_path should extract file_path from tool input."""
        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(
                tool_name="Write",
                tool_input={"file_path": "/workspace/test.py"},
            ),
        )
        assert event.get_file_path() == "/workspace/test.py"

    def test_get_file_path_none(self) -> None:
        """get_file_path should return None when tool_input is None."""
        event = HookEvent(event_type=EventType.PRE_TOOL_USE)
        assert event.get_file_path() is None

    def test_is_bash_tool(self) -> None:
        """is_bash_tool should return True for Bash tool events."""
        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(tool_name="Bash"),
        )
        assert event.is_bash_tool() is True

    def test_is_bash_tool_false(self) -> None:
        """is_bash_tool should return False for non-Bash tools."""
        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(tool_name="Write"),
        )
        assert event.is_bash_tool() is False

    def test_is_write_tool(self) -> None:
        """is_write_tool should return True for Write tool events."""
        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(tool_name="Write"),
        )
        assert event.is_write_tool() is True

    def test_is_edit_tool(self) -> None:
        """is_edit_tool should return True for Edit tool events."""
        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(tool_name="Edit"),
        )
        assert event.is_edit_tool() is True

    def test_is_read_tool(self) -> None:
        """is_read_tool should return True for Read tool events."""
        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(tool_name="Read"),
        )
        assert event.is_read_tool() is True

    def test_from_dict_full_format(self) -> None:
        """from_dict should parse complete event format."""
        data: dict[str, Any] = {
            "event": "PreToolUse",
            "hook_input": {
                "toolName": "Bash",
                "toolInput": {"command": "test"},
            },
        }
        event = HookEvent.from_dict(data)
        assert event.event_type == EventType.PRE_TOOL_USE
        assert event.tool_name == ToolName.BASH

    def test_from_dict_legacy_format(self) -> None:
        """from_dict should handle legacy format (no event wrapper)."""
        data: dict[str, Any] = {
            "toolName": "Bash",
            "toolInput": {"command": "test"},
        }
        event = HookEvent.from_dict(data)
        # Should default to PreToolUse for legacy format
        assert event.event_type == EventType.PRE_TOOL_USE
        assert event.tool_name == ToolName.BASH

    def test_frozen_model(self) -> None:
        """HookEvent should be immutable."""
        event = HookEvent(event_type=EventType.PRE_TOOL_USE)
        with pytest.raises(ValidationError):
            event.event_type = EventType.POST_TOOL_USE  # type: ignore[misc]

    def test_event_alias(self) -> None:
        """event field should work with 'event' alias."""
        data = {"event": "Stop"}
        event = HookEvent.model_validate(data)
        assert event.event_type == EventType.STOP

    def test_all_tool_check_methods(self) -> None:
        """All tool check methods should work correctly."""
        tools = ["Bash", "Write", "Edit", "Read", "Glob"]
        for tool in tools:
            event = HookEvent(
                event_type=EventType.PRE_TOOL_USE,
                hook_input=HookInput(tool_name=tool),
            )

            # Only the matching method should return True
            assert event.is_bash_tool() == (tool == ToolName.BASH)
            assert event.is_write_tool() == (tool == ToolName.WRITE)
            assert event.is_edit_tool() == (tool == "Edit")
            assert event.is_read_tool() == (tool == "Read")


class TestEventTypeStatusLine:
    """Tests for STATUS_LINE event type."""

    def test_status_line_event_exists(self) -> None:
        """STATUS_LINE event type should exist."""
        assert EventType.STATUS_LINE == "Status"

    def test_status_line_from_string(self) -> None:
        """STATUS_LINE should be parseable from string."""
        assert EventType.from_string("Status") == EventType.STATUS_LINE
        assert EventType.from_string("status") == EventType.STATUS_LINE
        assert EventType.from_string("status_line") == EventType.STATUS_LINE
