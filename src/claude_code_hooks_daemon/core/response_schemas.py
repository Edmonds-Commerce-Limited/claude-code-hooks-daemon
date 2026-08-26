"""JSON schemas for Claude Code hook responses.

These schemas define the EXACT structure required by Claude Code for each hook event type.
Used for validation in tests to ensure handlers return compliant responses.

References:
- Claude Code Hooks API documentation
- Hook event types defined in HookEventType enum
"""

from typing import Any, Final

from claude_code_hooks_daemon.constants.events import (
    STATUS_LINE_JSON_KEY,
    STATUS_SCHEMA_KEY,
    wired_event_metas,
)

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
                    "enum": ["allow", "deny", "ask", "defer"],
                },
                "permissionDecisionReason": {"type": "string"},
                # Replaces the tool's ENTIRE input object before execution
                # (Plan 00271 item 1).
                "updatedInput": {"type": "object", "additionalProperties": True},
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
        # Top-level decision field for blocking
        "decision": {"type": "string", "const": "block"},
        "reason": {"type": "string"},
        # hookSpecificOutput.additionalContext for non-blocking advisory
        # feedback that continues the conversation (Claude Code hooks docs)
        "hookSpecificOutput": {
            "type": "object",
            "properties": {
                "hookEventName": {"type": "string", "enum": ["Stop", "SubagentStop"]},
                "additionalContext": {"type": "string"},
            },
            "required": ["hookEventName"],
            "additionalProperties": False,
        },
    },
    "required": [],  # All fields are optional
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
                        # The documented enum is allow | deny ONLY — there is
                        # no "ask" outcome on PermissionRequest (the docs'
                        # decision.behavior table; Plan 00271 audit item 3).
                        "behavior": {
                            "type": "string",
                            "enum": ["allow", "deny"],
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
# CRITICAL: Claude Code does NOT accept hookSpecificOutput for SessionStart
# Only systemMessage is valid
# =============================================================================

SESSION_START_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "systemMessage": {"type": "string"},
    },
    "additionalProperties": False,
}

# =============================================================================
# SessionEnd Hook Response Schema
# CRITICAL: Claude Code does NOT accept hookSpecificOutput for SessionEnd
# Only systemMessage is valid
# =============================================================================

SESSION_END_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "systemMessage": {"type": "string"},
    },
    "additionalProperties": False,
}

# =============================================================================
# PreCompact Hook Response Schema
# The docs put PreCompact in the top-level `decision: "block"` group (a hook
# can block compaction — Plan 00271 audit item 7). `systemMessage` is
# accepted but DISCARDED by Claude Code for this event (dead-letter, per the
# docs); it stays declared because the advisory path still emits it, and the
# dead letter is recorded in contracts/claude-code-hooks/ALLOWLIST.yaml.
# =============================================================================

PRE_COMPACT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "systemMessage": {"type": "string"},
        "decision": {"type": "string", "const": "block"},
        "reason": {"type": "string"},
    },
    "additionalProperties": False,
}

# =============================================================================
# UserPromptSubmit Hook Response Schema (identical structure to SessionStart)
# =============================================================================

USER_PROMPT_SUBMIT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        # Documented top-level blocking: decision "block" + reason (shown to
        # the user, not added to context) — Plan 00271 audit item 5.
        "decision": {"type": "string", "const": "block"},
        "reason": {"type": "string"},
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
# Notification Hook Response Schema
# CRITICAL: Claude Code does NOT accept hookSpecificOutput for Notification
# Only systemMessage is valid
# =============================================================================

NOTIFICATION_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "systemMessage": {"type": "string"},
    },
    "additionalProperties": False,
}

# =============================================================================
# Status Hook Response Schema
# CRITICAL: Status emits a plain-text payload {"text": "..."} (see
# HookResult.to_json), NOT hookSpecificOutput or a decision field.
# =============================================================================

STATUS_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
    },
    "required": ["text"],
    "additionalProperties": False,
}

# =============================================================================
# Schema Registry - Map event names to schemas
# =============================================================================

# =============================================================================
# WorktreeCreate / WorktreeRemove Hook Response Schemas
# =============================================================================
# These two are the ONLY wired events outside the eleven-event baseline that
# ship a built-in handler, so they are the only ones the permissive fail-open
# schema below must not cover — its premise is that such an event emits nothing
# but a passthrough. They emit a real response, and one of them emits a bespoke
# key nothing else does.
#
# Both fall through to _format_system_message_response, which DELIBERATELY emits
# {"decision": ...} for a DENY/ASK so that validation rejects it. Under a
# permissive schema that tripwire was disarmed: the payload that fails on
# SessionStart passed here. additionalProperties: False re-arms it.

WORKTREE_CREATE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        # Claude Code parses this hook's stdout as a raw path (Plan 00188), so
        # this key is the entire purpose of the event.
        "worktreePath": {"type": "string"},
        "systemMessage": {"type": "string"},
    },
    "additionalProperties": False,
}

# No path: a removal has none to report. Kept separate from the create schema so
# the distinction is enforced rather than merely described.
WORKTREE_REMOVE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "systemMessage": {"type": "string"},
    },
    "additionalProperties": False,
}

# =============================================================================
# Wired-extra blockable events (Plan 00271 audit item 9)
# =============================================================================
# The docs give these events real blocking mechanisms. A DENY used to fall
# through to the systemMessage formatter, emitting the undefined token
# {"decision": "deny"} — which VALIDATED under the permissive fail-open schema
# and was silently ignored by Claude Code. These bespoke schemas re-arm the
# tripwire: "decision" is constrained to the documented "block" (or absent
# entirely for the continue-false events), so the old token cannot validate.

#: The five universal output fields the docs define on every event.
_UNIVERSAL_OUTPUT_PROPERTIES: Final[dict[str, Any]] = {
    "continue": {"type": "boolean"},
    "stopReason": {"type": "string"},
    "suppressOutput": {"type": "boolean"},
    "systemMessage": {"type": "string"},
    "terminalSequence": {"type": "string"},
}


def _top_level_block_schema(
    event_name: str, *, discard: tuple[str, ...] = (), with_context: bool = False
) -> dict[str, Any]:
    """A bespoke schema for a documented top-level ``decision: "block"`` event.

    Args:
        event_name: The wire event name (for hookSpecificOutput.hookEventName).
        discard: Universal fields the docs say Claude Code DISCARDS for this
            event and the daemon never emits (left undeclared so an emission is
            rejected rather than dead-lettered) — except ``systemMessage``,
            which the daemon's advisory path still emits where accepted.
        with_context: Whether the docs define hookSpecificOutput.additionalContext.
    """
    properties: dict[str, Any] = {
        name: spec for name, spec in _UNIVERSAL_OUTPUT_PROPERTIES.items() if name not in discard
    }
    properties["decision"] = {"type": "string", "const": "block"}
    properties["reason"] = {"type": "string"}
    if with_context:
        properties["hookSpecificOutput"] = {
            "type": "object",
            "properties": {
                "hookEventName": {"type": "string", "const": event_name},
                "additionalContext": {"type": "string"},
            },
            "required": ["hookEventName"],
            "additionalProperties": False,
        }
    return {"type": "object", "properties": properties, "additionalProperties": False}


#: TeammateIdle / TaskCompleted: blocking is ``continue: false`` + stopReason.
#: No top-level ``decision`` exists for them, and additionalProperties: False is
#: what rejects the historical ``{"decision": "deny"}`` shape.
_CONTINUE_FALSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": dict(_UNIVERSAL_OUTPUT_PROPERTIES),
    "additionalProperties": False,
}

USER_PROMPT_EXPANSION_SCHEMA: Final[dict[str, Any]] = _top_level_block_schema(
    "UserPromptExpansion", with_context=True
)
POST_TOOL_USE_FAILURE_SCHEMA: Final[dict[str, Any]] = _top_level_block_schema(
    "PostToolUseFailure", with_context=True
)
POST_TOOL_BATCH_SCHEMA: Final[dict[str, Any]] = _top_level_block_schema(
    "PostToolBatch", with_context=True
)
# TaskCreated: docs say continue is ignored, so it stays undeclared.
TASK_CREATED_SCHEMA: Final[dict[str, Any]] = _top_level_block_schema(
    "TaskCreated", discard=("continue",)
)
# ConfigChange: docs discard continue outright; systemMessage is accepted but
# discarded (dead-letter) — kept declared because the advisory path emits it.
CONFIG_CHANGE_SCHEMA: Final[dict[str, Any]] = _top_level_block_schema(
    "ConfigChange", discard=("continue",)
)
TEAMMATE_IDLE_SCHEMA: Final[dict[str, Any]] = _CONTINUE_FALSE_SCHEMA
TASK_COMPLETED_SCHEMA: Final[dict[str, Any]] = _CONTINUE_FALSE_SCHEMA

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
    "Status": STATUS_SCHEMA,
    "WorktreeCreate": WORKTREE_CREATE_SCHEMA,
    "WorktreeRemove": WORKTREE_REMOVE_SCHEMA,
    "UserPromptExpansion": USER_PROMPT_EXPANSION_SCHEMA,
    "PostToolUseFailure": POST_TOOL_USE_FAILURE_SCHEMA,
    "PostToolBatch": POST_TOOL_BATCH_SCHEMA,
    "TaskCreated": TASK_CREATED_SCHEMA,
    "ConfigChange": CONFIG_CHANGE_SCHEMA,
    "TeammateIdle": TEAMMATE_IDLE_SCHEMA,
    "TaskCompleted": TASK_COMPLETED_SCHEMA,
}


def _permissive_response_schema() -> dict[str, Any]:
    """A fail-open response schema for a wired event with no bespoke schema.

    Newly-wired events (Plan 00170) ship no built-in handler, so the daemon only
    ever emits a passthrough response (``{}`` for an empty chain, or an advisory
    ``systemMessage`` / ``hookSpecificOutput`` if a client attaches a handler).
    Accept any object rather than constraining a contract we do not yet exercise.
    """
    return {
        "type": "object",
        "additionalProperties": True,
    }


# Auto-fill: every WIRED event must have a response schema, and get_response_schema
# RAISES on an unknown event. Bespoke schemas above win; any wired event lacking
# one gets a permissive fail-open schema. At the 11-event baseline this adds
# nothing; each Plan 00170 wiring flip picks up a schema here with no manual edit.
for _meta in wired_event_metas():
    _schema_key = STATUS_SCHEMA_KEY if _meta.json_key == STATUS_LINE_JSON_KEY else _meta.json_key
    RESPONSE_SCHEMAS.setdefault(_schema_key, _permissive_response_schema())


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
