"""JSON schemas for Claude Code hook responses.

These schemas define the EXACT structure required by Claude Code for each hook event type.
Used for validation in tests to ensure handlers return compliant responses.

References:
- Claude Code Hooks API documentation
- Hook event types defined in HookEventType enum
"""

from typing import Any, Final

# =============================================================================
# PreToolUse Hook Response Schema
# =============================================================================

PRE_TOOL_USE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "hookSpecificOutput": {
            "type": "object",
            "properties": {
                "hookEventName": {"type": "string", "const": "PreToolUse"},
                "permissionDecision": {
                    "type": "string",
                    "enum": ["allow", "deny", "ask"],
                },
                "permissionDecisionReason": {"type": "string"},
                "additionalContext": {"type": "string"},
                "guidance": {"type": "string"},
            },
            "required": ["hookEventName"],
            "additionalProperties": False,
        }
    },
    "additionalProperties": False,
}

# =============================================================================
# PostToolUse Hook Response Schema
# =============================================================================

POST_TOOL_USE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        # Top-level decision field (NOT in hookSpecificOutput)
        "decision": {"type": "string", "const": "block"},
        "reason": {"type": "string"},
        "hookSpecificOutput": {
            "type": "object",
            "properties": {
                "hookEventName": {"type": "string", "const": "PostToolUse"},
                "additionalContext": {"type": "string"},
                "guidance": {"type": "string"},
            },
            "required": ["hookEventName"],
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}

# =============================================================================
# Stop Hook Response Schema
# =============================================================================

STOP_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        # Top-level decision field only (no hookSpecificOutput)
        "decision": {"type": "string", "const": "block"},
        "reason": {"type": "string"},
    },
    "required": [],  # Both fields are optional
    "additionalProperties": False,
}

# =============================================================================
# SubagentStop Hook Response Schema (identical to Stop)
# =============================================================================

SUBAGENT_STOP_SCHEMA: Final[dict[str, Any]] = STOP_SCHEMA

# =============================================================================
# PermissionRequest Hook Response Schema
# =============================================================================

PERMISSION_REQUEST_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "hookSpecificOutput": {
            "type": "object",
            "properties": {
                "hookEventName": {"type": "string", "const": "PermissionRequest"},
                "decision": {
                    "type": "object",
                    "properties": {
                        "behavior": {
                            "type": "string",
                            "enum": ["allow", "deny", "ask"],
                        },
                        "updatedInput": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["behavior"],
                    "additionalProperties": False,
                },
                "additionalContext": {"type": "string"},
                "guidance": {"type": "string"},
            },
            "required": ["hookEventName"],
            "additionalProperties": False,
        }
    },
    "additionalProperties": False,
}

# =============================================================================
# SessionStart Hook Response Schema
# =============================================================================

SESSION_START_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "hookSpecificOutput": {
            "type": "object",
            "properties": {
                "hookEventName": {"type": "string", "const": "SessionStart"},
                "additionalContext": {"type": "string"},
                "guidance": {"type": "string"},
            },
            "required": ["hookEventName"],
            "additionalProperties": False,
        }
    },
    "additionalProperties": False,
}

# =============================================================================
# SessionEnd Hook Response Schema (identical to SessionStart)
# =============================================================================

SESSION_END_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "hookSpecificOutput": {
            "type": "object",
            "properties": {
                "hookEventName": {"type": "string", "const": "SessionEnd"},
                "additionalContext": {"type": "string"},
                "guidance": {"type": "string"},
            },
            "required": ["hookEventName"],
            "additionalProperties": False,
        }
    },
    "additionalProperties": False,
}

# =============================================================================
# PreCompact Hook Response Schema (identical structure to SessionStart)
# =============================================================================

PRE_COMPACT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "hookSpecificOutput": {
            "type": "object",
            "properties": {
                "hookEventName": {"type": "string", "const": "PreCompact"},
                "additionalContext": {"type": "string"},
                "guidance": {"type": "string"},
            },
            "required": ["hookEventName"],
            "additionalProperties": False,
        }
    },
    "additionalProperties": False,
}

# =============================================================================
# UserPromptSubmit Hook Response Schema (identical structure to SessionStart)
# =============================================================================

USER_PROMPT_SUBMIT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "hookSpecificOutput": {
            "type": "object",
            "properties": {
                "hookEventName": {"type": "string", "const": "UserPromptSubmit"},
                "additionalContext": {"type": "string"},
                "guidance": {"type": "string"},
            },
            "required": ["hookEventName"],
            "additionalProperties": False,
        }
    },
    "additionalProperties": False,
}

# =============================================================================
# Notification Hook Response Schema (identical structure to SessionStart)
# =============================================================================

NOTIFICATION_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "hookSpecificOutput": {
            "type": "object",
            "properties": {
                "hookEventName": {"type": "string", "const": "Notification"},
                "additionalContext": {"type": "string"},
                "guidance": {"type": "string"},
            },
            "required": ["hookEventName"],
            "additionalProperties": False,
        }
    },
    "additionalProperties": False,
}

# =============================================================================
# Schema Registry - Map event names to schemas
# =============================================================================

RESPONSE_SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "PreToolUse": PRE_TOOL_USE_SCHEMA,
    "PostToolUse": POST_TOOL_USE_SCHEMA,
    "Stop": STOP_SCHEMA,
    "SubagentStop": SUBAGENT_STOP_SCHEMA,
    "PermissionRequest": PERMISSION_REQUEST_SCHEMA,
    "SessionStart": SESSION_START_SCHEMA,
    "SessionEnd": SESSION_END_SCHEMA,
    "PreCompact": PRE_COMPACT_SCHEMA,
    "UserPromptSubmit": USER_PROMPT_SUBMIT_SCHEMA,
    "Notification": NOTIFICATION_SCHEMA,
}


def get_response_schema(event_name: str) -> dict[str, Any]:
    """Get the JSON schema for a specific hook event's response.

    Args:
        event_name: Hook event name (e.g., "PreToolUse", "PostToolUse")

    Returns:
        JSON schema dictionary

    Raises:
        ValueError: If event name is unknown
    """
    if event_name not in RESPONSE_SCHEMAS:
        raise ValueError(
            f"Unknown hook event: {event_name}. "
            f"Valid events: {', '.join(RESPONSE_SCHEMAS.keys())}"
        )
    return RESPONSE_SCHEMAS[event_name]


def validate_response(event_name: str, response: dict[str, Any]) -> list[str]:
    """Validate a hook response against its event's schema.

    Args:
        event_name: Hook event name
        response: Response dictionary to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    try:
        from jsonschema import Draft7Validator
    except ImportError:
        return ["jsonschema not installed - cannot validate responses"]

    schema = get_response_schema(event_name)
    validator = Draft7Validator(schema)
    errors = []

    for error in validator.iter_errors(response):
        # Build a human-readable path to the error
        path = ".".join(str(p) for p in error.path) if error.path else "root"
        errors.append(f"{path}: {error.message}")

    return errors


def is_valid_response(event_name: str, response: dict[str, Any]) -> bool:
    """Check if a response is valid for the given event.

    Args:
        event_name: Hook event name
        response: Response dictionary to validate

    Returns:
        True if valid, False otherwise
    """
    return len(validate_response(event_name, response)) == 0
