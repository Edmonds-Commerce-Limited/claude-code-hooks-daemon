"""Constants module - Single source of truth for all identifiers and values.

This module provides centralized constants for:
- Handler identifiers and metadata (HandlerID, HandlerKey)
- Event type identifiers (EventID, EventKey)
- Priority values (Priority)
- Timeout values (Timeout)
- Path constants (DaemonPath, ProjectPath)
- Handler tags (HandlerTag, TagLiteral)
- Tool names (ToolName, ToolNameLiteral)
- Config keys (ConfigKey)
- Protocol fields (HookInputField, HookOutputField, PermissionDecision)
- Validation limits (ValidationLimit)
- Formatting limits (FormatLimit)

Usage:
    from claude_code_hooks_daemon.constants import (
        HandlerID, Priority, HandlerTag, ToolName
    )

    handler = MyHandler(
        handler_id=HandlerID.DESTRUCTIVE_GIT,
        priority=Priority.DESTRUCTIVE_GIT,
        tags=[HandlerTag.SAFETY, HandlerTag.GIT],
    )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        tool_name = hook_input.get(HookInputField.TOOL_NAME)  # "tool_name"
        return tool_name == ToolName.BASH  # "Bash"

Design Principles:
- NO MAGIC STRINGS: All identifiers come from this module
- NO MAGIC NUMBERS: All priorities, timeouts, and thresholds defined here
- DRY: Single source of truth for all naming and values
- TYPE SAFETY: Use Literal types for compile-time checking
"""

from claude_code_hooks_daemon.constants.config import ConfigKey
from claude_code_hooks_daemon.constants.events import EventID, EventIDMeta, EventKey
from claude_code_hooks_daemon.constants.formatting import FormatLimit
from claude_code_hooks_daemon.constants.handlers import HandlerID, HandlerIDMeta, HandlerKey
from claude_code_hooks_daemon.constants.paths import DaemonPath, ProjectPath
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.protocol import (
    HookInputField,
    HookOutputField,
    PermissionDecision,
)
from claude_code_hooks_daemon.constants.tags import HandlerTag, TagLiteral
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.constants.tools import ToolName, ToolNameLiteral
from claude_code_hooks_daemon.constants.validation import ValidationLimit

__all__ = [
    # Config key constants
    "ConfigKey",
    # Path constants
    "DaemonPath",
    # Event constants
    "EventID",
    "EventIDMeta",
    "EventKey",
    # Formatting limit constants
    "FormatLimit",
    # Handler constants
    "HandlerID",
    "HandlerIDMeta",
    "HandlerKey",
    # Tag constants
    "HandlerTag",
    # Protocol field constants
    "HookInputField",
    "HookOutputField",
    "PermissionDecision",
    # Priority constants
    "Priority",
    "ProjectPath",
    "TagLiteral",
    # Timeout constants
    "Timeout",
    # Tool name constants
    "ToolName",
    "ToolNameLiteral",
    # Validation limit constants
    "ValidationLimit",
]
