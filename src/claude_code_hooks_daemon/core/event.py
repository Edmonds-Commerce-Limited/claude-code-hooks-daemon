"""HookEvent model for standardised event representation.

This module provides Pydantic models for representing hook events
from Claude Code with full type safety and validation.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(StrEnum):
    """Supported Claude Code hook event types."""

    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    PRE_COMPACT = "PreCompact"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PERMISSION_REQUEST = "PermissionRequest"
    NOTIFICATION = "Notification"
    STOP = "Stop"
    SUBAGENT_STOP = "SubagentStop"
    STATUS_LINE = "Status"

    @classmethod
    def from_string(cls, value: str) -> "EventType":
        """Convert string to EventType, case-insensitive.

        Args:
            value: Event type string (e.g., "PreToolUse", "pre_tool_use")

        Returns:
            Matching EventType enum member

        Raises:
            ValueError: If no matching event type found
        """
        # Try exact match first
        for member in cls:
            if member.value == value:
                return member

        # Try snake_case conversion
        normalised = value.lower().replace("_", "")
        for member in cls:
            if member.value.lower().replace("_", "") == normalised:
                return member

        valid_types = ", ".join(m.value for m in cls)
        raise ValueError(f"Unknown event type: {value}. Valid types: {valid_types}")


class ToolInput(BaseModel):
    """Tool input data from Claude Code.

    Represents the tool-specific input data, with common fields
    extracted for convenience.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    command: str | None = Field(default=None, description="Command for Bash tool")
    file_path: str | None = Field(default=None, description="File path for Read/Write/Edit tools")
    pattern: str | None = Field(default=None, description="Pattern for Glob/Grep tools")
    content: str | None = Field(default=None, description="Content for Write tool")
    old_string: str | None = Field(default=None, description="Old string for Edit tool")
    new_string: str | None = Field(default=None, description="New string for Edit tool")


class HookInput(BaseModel):
    """Hook input payload from Claude Code.

    Contains all information about the hook invocation,
    including tool name, input data, and session context.
    """

    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)

    tool_name: str | None = Field(default=None, alias="toolName")
    tool_input: dict[str, Any] | None = Field(default=None, alias="toolInput")
    session_id: str | None = Field(default=None, alias="sessionId")
    transcript_path: str | None = Field(default=None, alias="transcriptPath")
    message: str | None = Field(default=None, description="For Notification events")
    prompt: str | None = Field(default=None, description="For UserPromptSubmit events")

    def get_tool_input_model(self) -> ToolInput:
        """Get tool input as a ToolInput model for typed access.

        Returns:
            ToolInput model with tool-specific fields
        """
        if self.tool_input is None:
            return ToolInput()
        return ToolInput.model_validate(self.tool_input)


class HookEvent(BaseModel):
    """Complete hook event with type and input data.

    This is the primary model for representing hook events
    throughout the daemon system.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    event_type: EventType = Field(alias="event")
    hook_input: HookInput = Field(default_factory=HookInput)
    request_id: str | None = Field(default=None, description="Optional correlation ID")

    @property
    def tool_name(self) -> str | None:
        """Get tool name from hook input."""
        return self.hook_input.tool_name

    @property
    def tool_input(self) -> dict[str, Any] | None:
        """Get tool input dict from hook input."""
        return self.hook_input.tool_input

    @property
    def session_id(self) -> str | None:
        """Get session ID from hook input."""
        return self.hook_input.session_id

    def get_command(self) -> str | None:
        """Get command from Bash tool input.

        Returns:
            Command string or None if not a Bash tool event
        """
        if self.hook_input.tool_input is None:
            return None
        return self.hook_input.tool_input.get("command")

    def get_file_path(self) -> str | None:
        """Get file path from tool input.

        Returns:
            File path string or None if not present
        """
        if self.hook_input.tool_input is None:
            return None
        return self.hook_input.tool_input.get("file_path")

    def is_bash_tool(self) -> bool:
        """Check if this is a Bash tool event."""
        return self.hook_input.tool_name == "Bash"

    def is_write_tool(self) -> bool:
        """Check if this is a Write tool event."""
        return self.hook_input.tool_name == "Write"

    def is_edit_tool(self) -> bool:
        """Check if this is an Edit tool event."""
        return self.hook_input.tool_name == "Edit"

    def is_read_tool(self) -> bool:
        """Check if this is a Read tool event."""
        return self.hook_input.tool_name == "Read"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HookEvent":
        """Create HookEvent from dictionary.

        Handles legacy format where hook_input is the entire dict.

        Args:
            data: Dictionary with event data

        Returns:
            HookEvent instance
        """
        # Handle legacy format (no event wrapper)
        if "event" not in data and "hook_input" not in data:
            # Assume this is direct hook_input - use alias for Pydantic
            return cls.model_validate(
                {
                    "event": EventType.PRE_TOOL_USE.value,
                    "hook_input": data,
                }
            )

        return cls.model_validate(data)
