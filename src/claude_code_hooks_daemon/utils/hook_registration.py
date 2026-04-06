"""Hook registration validation utility.

Shared logic for validating Claude Code hook registrations in settings.json.
Used by both the SessionStart handler and the install validator.

Validates:
- All expected hook event types are registered
- No duplicate registrations across settings.json and settings.local.json
- Hook commands point to the correct scripts
"""

from __future__ import annotations

from claude_code_hooks_daemon.constants.events import EventID, EventIDMeta

# ---------------------------------------------------------------------------
# Single source of truth: expected hook events in settings.json
# ---------------------------------------------------------------------------
# Derived from EventID constants.  StatusLine uses a top-level "statusLine"
# key in settings.json rather than the "hooks" section, so it is excluded.

_STATUS_LINE_JSON_KEY = "StatusLine"


def _build_hook_events_map() -> dict[str, str]:
    """Build mapping of json_key -> bash_key for all hookable event types.

    Returns:
        Dict mapping PascalCase json_key to kebab-case bash_key
    """
    result: dict[str, str] = {}
    for name in dir(EventID):
        attr = getattr(EventID, name)
        if isinstance(attr, EventIDMeta) and attr.json_key != _STATUS_LINE_JSON_KEY:
            result[attr.json_key] = attr.bash_key
    return result


HOOK_EVENTS_IN_SETTINGS: dict[str, str] = _build_hook_events_map()


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------


def validate_settings_hooks(settings: dict[str, object]) -> list[str]:
    """Check that settings dict contains all expected hook event registrations.

    Args:
        settings: Parsed contents of settings.json

    Returns:
        List of issue descriptions (empty means all hooks are present)
    """
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}

    issues: list[str] = []
    for json_key in sorted(HOOK_EVENTS_IN_SETTINGS.keys()):
        if json_key not in hooks:
            issues.append(f"Missing hook registration for {json_key} in settings.json")
    return issues


def detect_duplicate_hooks(
    settings: dict[str, object],
    local_settings: dict[str, object],
) -> list[str]:
    """Detect hook events registered in BOTH settings.json and settings.local.json.

    A hook present in both files causes Claude Code to run the hook command
    twice per event, which is almost always unintentional.

    Args:
        settings: Parsed contents of settings.json
        local_settings: Parsed contents of settings.local.json

    Returns:
        List of duplicate descriptions (empty means no duplicates)
    """
    main_hooks = settings.get("hooks", {})
    local_hooks = local_settings.get("hooks", {})

    if not isinstance(main_hooks, dict) or not isinstance(local_hooks, dict):
        return []

    issues: list[str] = []
    for event_key in sorted(local_hooks.keys()):
        if event_key in main_hooks:
            issues.append(
                f"Duplicate hook: {event_key} is registered in both "
                f"settings.json and settings.local.json — hook will fire twice"
            )
    return issues


def validate_hook_commands(settings: dict[str, object]) -> list[str]:
    """Validate that hook commands point to the correct scripts.

    Checks that each hook event type has exactly one hook entry and that
    the command references the expected bash script name.

    Args:
        settings: Parsed contents of settings.json

    Returns:
        List of command issues (empty means all commands are correct)
    """
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return []

    issues: list[str] = []
    for json_key, expected_bash_key in sorted(HOOK_EVENTS_IN_SETTINGS.items()):
        event_hooks = hooks.get(json_key)
        if not event_hooks or not isinstance(event_hooks, list):
            continue  # Missing hooks are caught by validate_settings_hooks

        # Check for multiple hook entries (suspicious — usually a duplicate)
        if len(event_hooks) > 1:
            issues.append(
                f"{json_key} has {len(event_hooks)} hook entries "
                f"(expected 1) — likely duplicate registration"
            )
            continue

        # Extract the command from the single hook entry
        hook_entry = event_hooks[0]
        inner_hooks = hook_entry.get("hooks", [])
        if not inner_hooks:
            continue

        command = inner_hooks[0].get("command", "")
        # Check that the command ends with the expected script name
        expected_suffix = f"/.claude/hooks/{expected_bash_key}"
        if not command.endswith(expected_suffix):
            issues.append(
                f"{json_key} command does not end with {expected_suffix}: " f"got {command!r}"
            )

    return issues
