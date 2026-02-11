"""User-friendly formatting for Pydantic config validation errors.

Converts raw Pydantic ValidationError into actionable messages with
before/after examples for common upgrade-related config mistakes.
"""

import difflib
from typing import Any

from pydantic import ValidationError

# Fields that are valid on PluginConfig
_PLUGIN_VALID_FIELDS = frozenset({"path", "event_type", "handlers", "enabled"})

# Fields that are valid on HandlerConfig
_HANDLER_VALID_FIELDS = frozenset({"enabled", "priority", "options"})

# Error type constants from Pydantic
_ERROR_TYPE_MISSING = "missing"
_ERROR_TYPE_EXTRA = "extra_forbidden"

# Header for all config error messages
_ERROR_HEADER = "Config Error"


def format_validation_error(
    error: ValidationError,
    config: dict[str, Any] | None = None,
) -> str:
    """Format a Pydantic ValidationError into a user-friendly message.

    Produces actionable messages with before/after examples for common
    config mistakes (missing fields, typos, format errors).

    Args:
        error: The Pydantic ValidationError to format
        config: Optional original config dict for context

    Returns:
        User-friendly error message string
    """
    lines: list[str] = [f"{_ERROR_HEADER}: Configuration validation failed.", ""]

    for err in error.errors():
        location = _format_location(err["loc"])
        error_type = err["type"]
        message = err["msg"]

        if error_type == _ERROR_TYPE_MISSING:
            lines.extend(_format_missing_field(err, location))
        elif error_type == _ERROR_TYPE_EXTRA:
            lines.extend(_format_extra_field(err, location))
        else:
            lines.extend(_format_general_error(location, message))

        lines.append("")

    return "\n".join(lines).rstrip()


def _format_location(loc: tuple[str | int, ...]) -> str:
    """Format Pydantic error location tuple into a readable path.

    Args:
        loc: Pydantic error location tuple

    Returns:
        Dotted path string like 'plugins.plugins.0.event_type'
    """
    return ".".join(str(part) for part in loc)


def _format_missing_field(err: dict[str, Any], location: str) -> list[str]:
    """Format a 'field required' error with before/after example.

    Args:
        err: Pydantic error dict
        location: Formatted location string

    Returns:
        List of formatted message lines
    """
    field_name = str(err["loc"][-1]) if err["loc"] else "unknown"
    lines: list[str] = [f"  Missing required field '{field_name}' at: {location}"]

    # Special case: plugin missing event_type
    if field_name == "event_type" and "plugins" in location:
        lines.append("")
        lines.append("  Before (old format):")
        lines.append("    plugins:")
        lines.append("      plugins:")
        lines.append("        - path: my_module")
        lines.append("")
        lines.append("  After (new format - add event_type):")
        lines.append("    plugins:")
        lines.append("      plugins:")
        lines.append("        - path: my_module")
        lines.append("          event_type: pre_tool_use")

    return lines


def _format_extra_field(err: dict[str, Any], location: str) -> list[str]:
    """Format an 'extra fields not permitted' error with suggestion.

    Uses fuzzy matching to suggest the closest valid field name.

    Args:
        err: Pydantic error dict
        location: Formatted location string

    Returns:
        List of formatted message lines
    """
    field_name = str(err["loc"][-1]) if err["loc"] else "unknown"
    lines: list[str] = [f"  Unknown field '{field_name}' at: {location}"]

    # Determine which valid fields to check based on location
    if "handlers" in location:
        valid_fields = _HANDLER_VALID_FIELDS
    elif "plugins" in location:
        valid_fields = _PLUGIN_VALID_FIELDS
    else:
        valid_fields = frozenset()

    if valid_fields:
        matches = difflib.get_close_matches(field_name, valid_fields, n=1, cutoff=0.5)
        if matches:
            lines.append(f"  Did you mean: '{matches[0]}'?")
        else:
            lines.append(f"  Valid fields: {', '.join(sorted(valid_fields))}")

    return lines


def _format_general_error(location: str, message: str) -> list[str]:
    """Format a general validation error with field path.

    Args:
        location: Formatted location string
        message: Pydantic error message

    Returns:
        List of formatted message lines
    """
    return [f"  Field '{location}': {message}"]
