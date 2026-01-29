"""JSON schemas for Claude Code hook input validation.

These schemas define the EXACT structure of hook_input received from Claude Code
for each hook event type. Used for validation in the daemon server to catch
malformed events and wrong field names (e.g., tool_output vs tool_response).

CRITICAL: These schemas are based on REAL captured events from Claude Code,
not assumptions. See CLAUDE/Plan/002-fix-silent-handler-failures/ for analysis.

References:
- Real event captures from debug_hooks.sh sessions
- Hook event types defined in EventType enum
- POSTTOOLUSE_FIXTURE_VERIFICATION.md for PostToolUse structure
- USERPROMPTSUBMIT_FIXTURE_VERIFICATION.md for UserPromptSubmit structure
"""

from typing import Any, Final

# =============================================================================
# Common Base Fields
# =============================================================================

# Fields that appear in most/all hook events
_BASE_PROPERTIES: Final[dict[str, Any]] = {
    "session_id": {"type": "string"},
    "transcript_path": {"type": "string"},
    "cwd": {"type": "string"},
    "permission_mode": {"type": "string"},
    "hook_event_name": {"type": "string"},
}

# =============================================================================
# PreToolUse Hook Input Schema
# =============================================================================

PRE_TOOL_USE_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "required": ["tool_name", "hook_event_name"],
    "properties": {
        **_BASE_PROPERTIES,
        "hook_event_name": {"const": "PreToolUse"},
        "tool_name": {"type": "string"},
        "tool_input": {
            "type": "object",
            "description": "Tool-specific input (command, file_path, etc.)",
        },
        "tool_use_id": {"type": "string"},
    },
    "additionalProperties": True,  # Forward compatibility with new fields
}

# =============================================================================
# PostToolUse Hook Input Schema
# =============================================================================
# CRITICAL: Real events have "tool_response", NOT "tool_output"
# CRITICAL: Bash tool_response has NO "exit_code" field

POST_TOOL_USE_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "required": ["tool_name", "tool_response", "hook_event_name"],
    "properties": {
        **_BASE_PROPERTIES,
        "hook_event_name": {"const": "PostToolUse"},
        "tool_name": {"type": "string"},
        "tool_input": {
            "type": "object",
            "description": "Tool-specific input (command, file_path, etc.)",
        },
        "tool_response": {
            "type": "object",
            "description": "Tool-specific response structure (stdout, file, filenames, etc.)",
            # Note: Structure varies by tool - Bash, Read, Glob, Grep, etc.
        },
        "tool_use_id": {"type": "string"},
    },
    "additionalProperties": True,
    "not": {
        # Explicitly reject the WRONG field name
        "required": ["tool_output"]
    },
}

# =============================================================================
# PermissionRequest Hook Input Schema
# =============================================================================
# CRITICAL: Real events have "permission_suggestions" array,
# NOT "permission_type" or "resource" fields

PERMISSION_REQUEST_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "required": ["tool_name", "permission_suggestions", "hook_event_name"],
    "properties": {
        **_BASE_PROPERTIES,
        "hook_event_name": {"const": "PermissionRequest"},
        "tool_name": {"type": "string"},
        "tool_input": {
            "type": "object",
            "description": "Tool-specific input",
        },
        "permission_suggestions": {
            "type": "array",
            "description": "Array of permission suggestion objects",
            "items": {"type": "object"},
        },
    },
    "additionalProperties": True,
    "not": {
        # Explicitly reject the WRONG field names
        "anyOf": [
            {"required": ["permission_type"]},
            {"required": ["resource"]},
        ]
    },
}

# =============================================================================
# Notification Hook Input Schema
# =============================================================================
# CRITICAL: Real events have "notification_type", NOT "severity"

NOTIFICATION_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "required": ["notification_type", "hook_event_name"],
    "properties": {
        **_BASE_PROPERTIES,
        "hook_event_name": {"const": "Notification"},
        "notification_type": {
            "type": "string",
            "enum": ["permission_prompt", "idle_prompt", "auth_success"],
            "description": "Type of notification from Claude Code",
        },
        "message": {"type": "string"},
    },
    "additionalProperties": True,
    "not": {
        # Explicitly reject the WRONG field name
        "required": ["severity"]
    },
}

# =============================================================================
# SessionStart Hook Input Schema
# =============================================================================

SESSION_START_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "required": ["session_id", "hook_event_name"],
    "properties": {
        **_BASE_PROPERTIES,
        "hook_event_name": {"const": "SessionStart"},
    },
    "additionalProperties": True,
}

# =============================================================================
# SessionEnd Hook Input Schema
# =============================================================================

SESSION_END_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "required": ["session_id", "hook_event_name"],
    "properties": {
        **_BASE_PROPERTIES,
        "hook_event_name": {"const": "SessionEnd"},
    },
    "additionalProperties": True,
}

# =============================================================================
# PreCompact Hook Input Schema
# =============================================================================

PRE_COMPACT_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "required": ["hook_event_name"],
    "properties": {
        **_BASE_PROPERTIES,
        "hook_event_name": {"const": "PreCompact"},
    },
    "additionalProperties": True,
}

# =============================================================================
# UserPromptSubmit Hook Input Schema
# =============================================================================

USER_PROMPT_SUBMIT_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "required": ["prompt", "hook_event_name"],
    "properties": {
        **_BASE_PROPERTIES,
        "hook_event_name": {"const": "UserPromptSubmit"},
        "prompt": {"type": "string", "description": "User's submitted prompt text"},
    },
    "additionalProperties": True,
}

# =============================================================================
# Stop Hook Input Schema
# =============================================================================

STOP_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "required": ["hook_event_name"],
    "properties": {
        **_BASE_PROPERTIES,
        "hook_event_name": {"const": "Stop"},
    },
    "additionalProperties": True,
}

# =============================================================================
# SubagentStop Hook Input Schema
# =============================================================================

SUBAGENT_STOP_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "required": ["hook_event_name"],
    "properties": {
        **_BASE_PROPERTIES,
        "hook_event_name": {"const": "SubagentStop"},
        "subagent_id": {"type": "string"},
        "subagent_type": {"type": "string"},
    },
    "additionalProperties": True,
}

# =============================================================================
# Status Hook Input Schema
# =============================================================================

STATUS_LINE_INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "required": ["hook_event_name"],
    "properties": {
        "hook_event_name": {"type": "string", "const": "Status"},
        "session_id": {"type": "string"},
        "model": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "display_name": {"type": "string"},
            },
        },
        "context_window": {
            "type": "object",
            "properties": {
                "used_percentage": {"type": ["number", "null"]},
                "total_input_tokens": {"type": ["number", "null"]},
                "context_window_size": {"type": ["number", "null"]},
            },
        },
        "workspace": {
            "type": "object",
            "properties": {
                "current_dir": {"type": "string"},
                "project_dir": {"type": "string"},
            },
        },
        "cost": {"type": "object"},
    },
    "additionalProperties": True,
}

# =============================================================================
# Schema Registry - Map event names to input schemas
# =============================================================================

INPUT_SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "PreToolUse": PRE_TOOL_USE_INPUT_SCHEMA,
    "PostToolUse": POST_TOOL_USE_INPUT_SCHEMA,
    "PermissionRequest": PERMISSION_REQUEST_INPUT_SCHEMA,
    "Notification": NOTIFICATION_INPUT_SCHEMA,
    "SessionStart": SESSION_START_INPUT_SCHEMA,
    "SessionEnd": SESSION_END_INPUT_SCHEMA,
    "PreCompact": PRE_COMPACT_INPUT_SCHEMA,
    "UserPromptSubmit": USER_PROMPT_SUBMIT_INPUT_SCHEMA,
    "Stop": STOP_INPUT_SCHEMA,
    "SubagentStop": SUBAGENT_STOP_INPUT_SCHEMA,
    "Status": STATUS_LINE_INPUT_SCHEMA,
}


def get_input_schema(event_name: str) -> dict[str, Any] | None:
    """Get the JSON schema for a specific hook event's input.

    Args:
        event_name: Hook event name (e.g., "PreToolUse", "PostToolUse")

    Returns:
        JSON schema dictionary, or None if event name is unknown
    """
    return INPUT_SCHEMAS.get(event_name)


def validate_input(event_name: str, hook_input: dict[str, Any]) -> list[str]:
    """Validate hook_input against its event's schema.

    Args:
        event_name: Hook event name
        hook_input: Input dictionary to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    try:
        from jsonschema import Draft7Validator
    except ImportError:
        return ["jsonschema not installed - cannot validate inputs"]

    schema = get_input_schema(event_name)
    if schema is None:
        # Unknown event type - skip validation (fail-open)
        return []

    validator = Draft7Validator(schema)
    errors = []

    for error in validator.iter_errors(hook_input):
        # Build a human-readable path to the error
        path = ".".join(str(p) for p in error.path) if error.path else "root"
        errors.append(f"{path}: {error.message}")

    return errors


def is_valid_input(event_name: str, hook_input: dict[str, Any]) -> bool:
    """Check if hook_input is valid for the given event.

    Args:
        event_name: Hook event name
        hook_input: Input dictionary to validate

    Returns:
        True if valid, False otherwise
    """
    return len(validate_input(event_name, hook_input)) == 0
