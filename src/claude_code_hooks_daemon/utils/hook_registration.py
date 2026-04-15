"""Hook registration validation utility.

Shared logic for validating Claude Code hook registrations in settings.json.
Used by the SessionStart handler, install/upgrade validator, and health CLI.

Validates:
- All expected hook event types are registered
- No duplicate registrations across settings.json and settings.local.json
- Hook commands point to the correct daemon wrapper scripts
- settings.local.json contains NO hooks (policy: hooks are tracked in
  settings.json only)
- No legacy-style direct scripts that bypass the daemon — these should
  migrate to project-level handlers
"""

from __future__ import annotations

from claude_code_hooks_daemon.constants.events import EventID, EventIDMeta

# ---------------------------------------------------------------------------
# Single source of truth: expected hook events in settings.json
# ---------------------------------------------------------------------------
# Derived from EventID constants.  StatusLine uses a top-level "statusLine"
# key in settings.json rather than the "hooks" section, so it is excluded.

_STATUS_LINE_JSON_KEY = "StatusLine"

# Fragment that identifies a daemon-wrapper hook command.  Daemon-installed
# hooks always end with `/.claude/hooks/{bash_key}` — anything else is either
# a misconfiguration or a pre-daemon "legacy" inline script.
_DAEMON_WRAPPER_FRAGMENT = "/.claude/hooks/"


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


def detect_local_hooks_misplacement(local_settings: dict[str, object]) -> list[str]:
    """Detect ANY hooks registered in settings.local.json.

    Policy: hooks configuration must live exclusively in settings.json.
    settings.local.json is for per-developer overrides (permissions, IDE
    settings) and is typically git-ignored, so any hooks there are:

    - Not tracked in version control → invisible to teammates and CI
    - Easily mistaken for tracked config → confusing to debug
    - Likely to cause silent duplicate firing if the same key also exists
      in settings.json

    Args:
        local_settings: Parsed contents of settings.local.json

    Returns:
        List of issue descriptions (empty means local settings contain no hooks)
    """
    local_hooks = local_settings.get("hooks", {})
    if not isinstance(local_hooks, dict):
        return []

    issues: list[str] = []
    for event_key in sorted(local_hooks.keys()):
        issues.append(
            f"Hook '{event_key}' is registered in settings.local.json — "
            "hooks must live in settings.json only (move the entry there and "
            "delete it from settings.local.json)"
        )
    return issues


def detect_legacy_hook_commands(settings: dict[str, object]) -> list[str]:
    """Detect hook commands that bypass the daemon's wrapper scripts.

    Daemon-installed hooks invoke `.../.claude/hooks/{bash_key}` — thin bash
    wrappers that forward events over the Unix socket to the daemon.  Any
    other command shape (inline Python, raw shell, absolute paths to bespoke
    scripts) bypasses the daemon entirely and represents a "legacy-style"
    setup from before the daemon was installed.

    The supported way to add project-specific behaviour is project-level
    handlers — see `init-project-handlers`.  A legacy script should either
    be removed (if redundant) or ported to a project handler so that it:

    - Benefits from the daemon's priority/dispatch ordering
    - Participates in the daemon's logging and error handling
    - Can be unit-tested alongside the rest of the handler suite

    Args:
        settings: Parsed contents of a settings file (main or local)

    Returns:
        List of issue descriptions (empty means all commands go through the
        daemon wrapper)
    """
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return []

    issues: list[str] = []
    for event_key in sorted(hooks.keys()):
        event_hooks = hooks.get(event_key)
        if not isinstance(event_hooks, list):
            continue
        for hook_entry in event_hooks:
            if not isinstance(hook_entry, dict):
                continue
            inner_hooks = hook_entry.get("hooks", [])
            if not isinstance(inner_hooks, list):
                continue
            for command_entry in inner_hooks:
                if not isinstance(command_entry, dict):
                    continue
                command = command_entry.get("command", "")
                if not isinstance(command, str) or not command:
                    continue
                if _DAEMON_WRAPPER_FRAGMENT in command:
                    continue
                issues.append(
                    f"Hook '{event_key}' uses a legacy-style command "
                    f"that bypasses the hooks daemon: {command!r}. "
                    "Port it to a project-level handler via "
                    "`init-project-handlers` so it runs through the daemon."
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
