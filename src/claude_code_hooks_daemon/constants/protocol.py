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
    """Hook input field names (camelCase) - single source of truth.

    These are the field names that appear in hook input JSON from
    Claude Code CLI. The protocol uses camelCase for field names.

    Input Structure (varies by hook type):
        {
            "hookEventName": str,
            "toolName": str,          # PreToolUse, PostToolUse
            "toolInput": dict,        # PreToolUse, PostToolUse
            "toolOutput": dict,       # PostToolUse
            "sessionId": str,         # Most hooks
            "transcriptPath": str,    # Most hooks
            "message": str,           # UserPromptSubmit, SessionStart
            "prompt": str,            # Stop, SubagentStop
            ...
        }
    """

    # Common fields (present in most hooks)
    HOOK_EVENT_NAME = "hookEventName"
    SESSION_ID = "sessionId"
    TRANSCRIPT_PATH = "transcriptPath"

    # Tool-related fields (PreToolUse, PostToolUse)
    TOOL_NAME = "toolName"
    TOOL_INPUT = "toolInput"
    TOOL_OUTPUT = "toolOutput"

    # Message/prompt fields
    MESSAGE = "message"
    PROMPT = "prompt"

    # Session fields
    SESSION_METADATA = "sessionMetadata"
    SESSION_STATISTICS = "sessionStatistics"

    # Agent fields (subagent hooks)
    AGENT_ID = "agentId"
    AGENT_TYPE = "agentType"
    AGENT_TRANSCRIPT_PATH = "agentTranscriptPath"

    # Notification fields
    NOTIFICATION_TYPE = "notificationType"
    NOTIFICATION_DATA = "notificationData"

    # Permission fields
    PERMISSION_REQUEST = "permissionRequest"
    PERMISSION_TYPE = "permissionType"


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
