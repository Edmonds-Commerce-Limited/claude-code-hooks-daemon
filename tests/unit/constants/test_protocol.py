"""Tests for hook protocol field constants.

Tests that all protocol field constants match the actual field names
used in Claude Code's hook protocol (JSON contract).
"""


from claude_code_hooks_daemon.constants.protocol import (
    HookInputField,
    HookOutputField,
    PermissionDecision,
)


class TestHookInputFieldConstants:
    """Tests for hook input field constants."""

    def test_common_input_fields(self) -> None:
        """Test common fields present in most hook inputs."""
        assert HookInputField.HOOK_EVENT_NAME == "hook_event_name"
        assert HookInputField.SESSION_ID == "session_id"
        assert HookInputField.TRANSCRIPT_PATH == "transcript_path"

    def test_tool_related_fields(self) -> None:
        """Test tool-related input fields."""
        assert HookInputField.TOOL_NAME == "tool_name"
        assert HookInputField.TOOL_INPUT == "tool_input"
        assert HookInputField.TOOL_OUTPUT == "tool_output"

    def test_message_prompt_fields(self) -> None:
        """Test message and prompt fields."""
        assert HookInputField.MESSAGE == "message"
        assert HookInputField.PROMPT == "prompt"

    def test_session_fields(self) -> None:
        """Test session-related fields."""
        assert HookInputField.SESSION_METADATA == "session_metadata"
        assert HookInputField.SESSION_STATISTICS == "session_statistics"

    def test_agent_fields(self) -> None:
        """Test subagent-related fields."""
        assert HookInputField.AGENT_ID == "agent_id"
        assert HookInputField.AGENT_TYPE == "agent_type"
        assert HookInputField.AGENT_TRANSCRIPT_PATH == "agent_transcript_path"

    def test_notification_fields(self) -> None:
        """Test notification-related fields."""
        assert HookInputField.NOTIFICATION_TYPE == "notification_type"
        assert HookInputField.NOTIFICATION_DATA == "notification_data"

    def test_permission_fields(self) -> None:
        """Test permission-related fields."""
        assert HookInputField.PERMISSION_REQUEST == "permission_request"
        assert HookInputField.PERMISSION_TYPE == "permission_type"


class TestHookOutputFieldConstants:
    """Tests for hook output field constants."""

    def test_top_level_output_fields(self) -> None:
        """Test top-level output wrapper fields."""
        assert HookOutputField.HOOK_SPECIFIC_OUTPUT == "hookSpecificOutput"
        assert HookOutputField.HOOK_EVENT_NAME == "hookEventName"

    def test_decision_fields(self) -> None:
        """Test decision-related output fields."""
        assert HookOutputField.DECISION == "decision"
        assert HookOutputField.REASON == "reason"

    def test_context_fields(self) -> None:
        """Test context fields for LLM."""
        assert HookOutputField.ADDITIONAL_CONTEXT == "additionalContext"
        assert HookOutputField.GUIDANCE == "guidance"
        assert HookOutputField.WARNING == "warning"
        assert HookOutputField.ERROR == "error"

    def test_permission_decision_fields(self) -> None:
        """Test permission decision fields."""
        assert HookOutputField.PERMISSION_DECISION == "permissionDecision"
        assert HookOutputField.PERMISSION_DECISION_REASON == "permissionDecisionReason"

    def test_modification_fields(self) -> None:
        """Test modification-related fields."""
        assert HookOutputField.MODIFIED_INPUT == "modifiedInput"
        assert HookOutputField.MODIFIED_TOOL_INPUT == "modifiedToolInput"
        assert HookOutputField.MODIFIED_MESSAGE == "modifiedMessage"

    def test_status_line_fields(self) -> None:
        """Test status line fields."""
        assert HookOutputField.STATUS_LINE_LEFT == "statusLineLeft"
        assert HookOutputField.STATUS_LINE_RIGHT == "statusLineRight"
        assert HookOutputField.STATUS_LINE_CENTER == "statusLineCenter"


class TestPermissionDecisionConstants:
    """Tests for permission decision constants."""

    def test_permission_decision_values(self) -> None:
        """Test permission decision values."""
        assert PermissionDecision.ALLOW == "allow"
        assert PermissionDecision.DENY == "deny"
        assert PermissionDecision.MODIFY == "modify"


class TestProtocolFieldNaming:
    """Tests for protocol field naming conventions."""

    def test_input_fields_use_snake_case(self) -> None:
        """Test that input fields use snake_case format."""
        for key, value in vars(HookInputField).items():
            if not key.startswith("_") and isinstance(value, str):
                # Should be lowercase with underscores (snake_case)
                assert value.islower() or "_" in value, f"{key}={value} not snake_case"
                assert " " not in value, f"{key}={value} contains spaces"

    def test_output_fields_use_camelcase(self) -> None:
        """Test that output fields use camelCase format."""
        for key, value in vars(HookOutputField).items():
            if not key.startswith("_") and isinstance(value, str):
                # Should start with lowercase (camelCase)
                assert value[0].islower(), f"{key}={value} not camelCase"
                assert " " not in value, f"{key}={value} contains spaces"
                assert "_" not in value, f"{key}={value} uses underscores (should be camelCase)"

    def test_no_duplicate_input_fields(self) -> None:
        """Test that there are no duplicate input field values."""
        field_values = [
            value
            for key, value in vars(HookInputField).items()
            if not key.startswith("_") and isinstance(value, str)
        ]
        duplicates = [v for v in field_values if field_values.count(v) > 1]
        assert len(duplicates) == 0, f"Duplicate input fields: {duplicates}"

    def test_no_duplicate_output_fields(self) -> None:
        """Test that there are no duplicate output field values."""
        field_values = [
            value
            for key, value in vars(HookOutputField).items()
            if not key.startswith("_") and isinstance(value, str)
        ]
        duplicates = [v for v in field_values if field_values.count(v) > 1]
        assert len(duplicates) == 0, f"Duplicate output fields: {duplicates}"


class TestProtocolUsagePatterns:
    """Tests for protocol field usage patterns."""

    def test_input_field_access_pattern(self) -> None:
        """Test common pattern for accessing input fields."""
        hook_input = {
            HookInputField.TOOL_NAME: "Bash",
            HookInputField.TOOL_INPUT: {"command": "ls"},
        }
        assert hook_input[HookInputField.TOOL_NAME] == "Bash"
        assert HookInputField.TOOL_INPUT in hook_input
        # Verify snake_case format
        assert HookInputField.TOOL_NAME == "tool_name"

    def test_output_field_construction_pattern(self) -> None:
        """Test common pattern for constructing output."""
        output = {
            HookOutputField.DECISION: "deny",
            HookOutputField.REASON: "Blocked",
            HookOutputField.ADDITIONAL_CONTEXT: "Use absolute paths",
        }
        assert output[HookOutputField.DECISION] == "deny"
        assert output[HookOutputField.REASON] == "Blocked"

    def test_nested_output_pattern(self) -> None:
        """Test nested output structure pattern."""
        result = {
            HookOutputField.HOOK_SPECIFIC_OUTPUT: {
                HookOutputField.DECISION: "allow",
            }
        }
        assert HookOutputField.HOOK_SPECIFIC_OUTPUT in result
        inner = result[HookOutputField.HOOK_SPECIFIC_OUTPUT]
        assert inner[HookOutputField.DECISION] == "allow"


class TestCriticalProtocolFields:
    """Tests for critical protocol fields."""

    def test_required_input_fields(self) -> None:
        """Test most commonly used input fields."""
        assert HookInputField.TOOL_NAME == "tool_name"
        assert HookInputField.TOOL_INPUT == "tool_input"
        assert HookInputField.SESSION_ID == "session_id"

    def test_required_output_fields(self) -> None:
        """Test most commonly used output fields."""
        assert HookOutputField.DECISION == "decision"
        assert HookOutputField.REASON == "reason"
        assert HookOutputField.ADDITIONAL_CONTEXT == "additionalContext"


class TestProtocolExport:
    """Tests for module exports."""

    def test_all_exports(self) -> None:
        """Test that __all__ contains expected exports."""
        from claude_code_hooks_daemon.constants import protocol

        assert hasattr(protocol, "__all__")
        assert "HookInputField" in protocol.__all__
        assert "HookOutputField" in protocol.__all__
        assert "PermissionDecision" in protocol.__all__

    def test_protocol_importable_from_constants(self) -> None:
        """Test that protocol classes can be imported from constants package."""
        from claude_code_hooks_daemon.constants import HookInputField as ImportedInput
        from claude_code_hooks_daemon.constants import HookOutputField as ImportedOutput

        assert ImportedInput.TOOL_NAME == "tool_name"
        assert ImportedOutput.DECISION == "decision"


class TestDecisionValues:
    """Tests for decision value constants."""

    def test_permission_decision_values_are_strings(self) -> None:
        """Test that all decision values are strings."""
        assert isinstance(PermissionDecision.ALLOW, str)
        assert isinstance(PermissionDecision.DENY, str)
        assert isinstance(PermissionDecision.MODIFY, str)

    def test_permission_decision_values_are_lowercase(self) -> None:
        """Test that decision values are lowercase."""
        assert PermissionDecision.ALLOW.islower()
        assert PermissionDecision.DENY.islower()
        assert PermissionDecision.MODIFY.islower()
