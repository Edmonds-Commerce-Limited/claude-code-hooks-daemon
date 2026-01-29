"""Event type identifier constants - Single source of truth for all event types.

This module defines the canonical identifiers for all hook event types.
Each event type has four name formats:
- enum_value: SCREAMING_SNAKE_CASE (Python enum value)
- config_key: snake_case (YAML config key)
- bash_key: kebab-case (bash script names)
- json_key: PascalCase (JSON protocol format)

Usage:
    from claude_code_hooks_daemon.constants import EventID

    # Use in event type matching
    if event_type == EventID.PRE_TOOL_USE.config_key:
        # Handle pre-tool-use event
        pass
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class EventIDMeta:
    """Metadata for an event type identifier.

    Attributes:
        enum_value: Python enum value (SCREAMING_SNAKE_CASE)
        config_key: YAML config key (snake_case)
        bash_key: Bash script name (kebab-case)
        json_key: JSON protocol format (PascalCase)
    """

    enum_value: str
    config_key: str
    bash_key: str
    json_key: str


class EventID:
    """Single source of truth for all event type identifiers.

    Each constant provides all four naming formats for an event type.
    Use these instead of hardcoding event type names anywhere in the codebase.
    """

    PRE_TOOL_USE = EventIDMeta(
        enum_value="PRE_TOOL_USE",
        config_key="pre_tool_use",
        bash_key="pre-tool-use",
        json_key="PreToolUse",
    )

    POST_TOOL_USE = EventIDMeta(
        enum_value="POST_TOOL_USE",
        config_key="post_tool_use",
        bash_key="post-tool-use",
        json_key="PostToolUse",
    )

    SESSION_START = EventIDMeta(
        enum_value="SESSION_START",
        config_key="session_start",
        bash_key="session-start",
        json_key="SessionStart",
    )

    SESSION_END = EventIDMeta(
        enum_value="SESSION_END",
        config_key="session_end",
        bash_key="session-end",
        json_key="SessionEnd",
    )

    STOP = EventIDMeta(
        enum_value="STOP",
        config_key="stop",
        bash_key="stop",
        json_key="Stop",
    )

    SUBAGENT_STOP = EventIDMeta(
        enum_value="SUBAGENT_STOP",
        config_key="subagent_stop",
        bash_key="subagent-stop",
        json_key="SubagentStop",
    )

    USER_PROMPT_SUBMIT = EventIDMeta(
        enum_value="USER_PROMPT_SUBMIT",
        config_key="user_prompt_submit",
        bash_key="user-prompt-submit",
        json_key="UserPromptSubmit",
    )

    PRE_COMPACT = EventIDMeta(
        enum_value="PRE_COMPACT",
        config_key="pre_compact",
        bash_key="pre-compact",
        json_key="PreCompact",
    )

    NOTIFICATION = EventIDMeta(
        enum_value="NOTIFICATION",
        config_key="notification",
        bash_key="notification",
        json_key="Notification",
    )

    PERMISSION_REQUEST = EventIDMeta(
        enum_value="PERMISSION_REQUEST",
        config_key="permission_request",
        bash_key="permission-request",
        json_key="PermissionRequest",
    )

    STATUS_LINE = EventIDMeta(
        enum_value="STATUS_LINE",
        config_key="status_line",
        bash_key="status-line",
        json_key="StatusLine",
    )


# Type-safe event key literal (for mypy/type checking)
EventKey = Literal[
    "pre_tool_use",
    "post_tool_use",
    "session_start",
    "session_end",
    "stop",
    "subagent_stop",
    "user_prompt_submit",
    "pre_compact",
    "notification",
    "permission_request",
    "status_line",
]
