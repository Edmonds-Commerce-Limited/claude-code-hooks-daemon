"""Hook protocol field constants - single source of truth.

This module defines all JSON field names used in the hook protocol
between Claude Code CLI and the hooks daemon. These field names use
camelCase format as per the protocol specification.

Usage:
    from claude_code_hooks_daemon.constants import HookInputField, HookOutputField

    # In handler matches():
    tool_name = hook_input.get(HookInputField.TOOL_NAME)

    # In HookResult:
    return HookResult(
        decision=Decision.ALLOW,
        context={HookOutputField.GUIDANCE: "Use absolute paths"}
    )
"""

from __future__ import annotations


class HookInputField:
    """Hook input field names (snake_case) - single source of truth.

    These are the field names that appear in hook input JSON from
    Claude Code hooks daemon. The internal protocol uses snake_case.

    Input Structure (varies by hook type):
        {
            "hook_event_name": str,
            "tool_name": str,          # PreToolUse, PostToolUse
            "tool_input": dict,        # PreToolUse, PostToolUse
            "tool_output": dict,       # PostToolUse
            "session_id": str,         # Most hooks
            "transcript_path": str,    # Most hooks
            "message": str,            # UserPromptSubmit, SessionStart
            "prompt": str,             # Stop, SubagentStop
            ...
        }
    """

    # Common fields (present in most hooks)
    HOOK_EVENT_NAME = "hook_event_name"
    SESSION_ID = "session_id"
    TRANSCRIPT_PATH = "transcript_path"
    CWD = "cwd"
    PERMISSION_MODE = "permission_mode"

    # Tool-related fields (PreToolUse, PostToolUse)
    TOOL_NAME = "tool_name"
    TOOL_INPUT = "tool_input"
    TOOL_OUTPUT = "tool_output"
    TOOL_USE_ID = "tool_use_id"

    # Message/prompt fields
    MESSAGE = "message"
    PROMPT = "prompt"

    # Session fields
    SESSION_METADATA = "session_metadata"
    SESSION_STATISTICS = "session_statistics"

    # Agent fields (subagent hooks)
    AGENT_ID = "agent_id"
    AGENT_TYPE = "agent_type"
    AGENT_TRANSCRIPT_PATH = "agent_transcript_path"

    # Notification fields
    NOTIFICATION_TYPE = "notification_type"
    NOTIFICATION_DATA = "notification_data"

    # Permission fields
    PERMISSION_REQUEST = "permission_request"
    PERMISSION_TYPE = "permission_type"


class HookOutputField:
    """Hook output field names (camelCase) - single source of truth.

    These are the field names that can appear in hook output JSON
    returned to Claude Code CLI. The protocol uses camelCase for field names.

    Output Structure (varies by hook type):
        {
            "hookSpecificOutput": {
                "decision": str,             # "allow" | "deny" | "modify"
                "reason": str,               # Optional explanation
                "additionalContext": str,    # Optional context for LLM
                "guidance": str,             # Optional guidance
                "modifiedInput": dict,       # For "modify" decision
                ...
            }
        }
    """

    # Top-level output wrapper
    HOOK_SPECIFIC_OUTPUT = "hookSpecificOutput"
    HOOK_EVENT_NAME = "hookEventName"

    # Decision fields
    DECISION = "decision"
    REASON = "reason"

    # Context fields for LLM
    ADDITIONAL_CONTEXT = "additionalContext"
    GUIDANCE = "guidance"
    WARNING = "warning"
    ERROR = "error"

    # Permission decision fields
    PERMISSION_DECISION = "permissionDecision"
    PERMISSION_DECISION_REASON = "permissionDecisionReason"

    # Modification fields (for "modify" decision)
    MODIFIED_INPUT = "modifiedInput"
    MODIFIED_TOOL_INPUT = "modifiedToolInput"
    MODIFIED_MESSAGE = "modifiedMessage"

    # Status line fields
    STATUS_LINE_LEFT = "statusLineLeft"
    STATUS_LINE_RIGHT = "statusLineRight"
    STATUS_LINE_CENTER = "statusLineCenter"


# Decision values (from hook_result.py Decision enum)
class PermissionDecision:
    """Permission decision values for permission hooks."""

    ALLOW = "allow"
    DENY = "deny"
    MODIFY = "modify"


__all__ = ["HookInputField", "HookOutputField", "PermissionDecision"]
