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

from dataclasses import dataclass, field
from typing import Any

from claude_code_hooks_daemon.constants.events import EventID, wired_event_metas

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
    """Build mapping of json_key -> bash_key for all WIRED hookable event types.

    Only ``wired=True`` events are included: catalogued-but-not-yet-wired events
    (Plan 00170 burn-down) have no forwarder or settings registration yet, so
    requiring them here would make ``hook_registration_checker`` flag a missing
    registration for a hook that deliberately does not exist yet. StatusLine is
    excluded because it registers under the top-level ``statusLine`` key rather
    than the ``hooks`` section.

    Returns:
        Dict mapping PascalCase json_key to kebab-case bash_key
    """
    return {
        meta.json_key: meta.bash_key
        for meta in wired_event_metas()
        if meta.json_key != _STATUS_LINE_JSON_KEY
    }


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


def _collect_command_hook_commands(event_hooks: list[object]) -> list[str]:
    """Return the command string of every ``type: command`` hook for one event.

    Walks all entries and all inner hooks, because an event may legally carry
    several of each. A hook with no ``command`` key is a native
    ``prompt``/``agent`` hook and is deliberately skipped — it is not a daemon
    registration and must not be counted as one.

    Every level is isinstance-guarded (mirroring ``detect_legacy_hook_commands``)
    so a malformed settings.json is diagnosed rather than crashing the validator
    that exists to diagnose it.
    """
    commands: list[str] = []
    for hook_entry in event_hooks:
        if not isinstance(hook_entry, dict):
            continue
        inner_hooks = hook_entry.get("hooks", [])
        if not inner_hooks or not isinstance(inner_hooks, list):
            continue
        for command_entry in inner_hooks:
            if not isinstance(command_entry, dict):
                continue
            if _HOOK_COMMAND_KEY not in command_entry:
                continue  # a native prompt/agent hook, not a daemon registration
            command = command_entry.get(_HOOK_COMMAND_KEY)
            if not isinstance(command, str):
                continue
            commands.append(command)
    return commands


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

        # Collect every COMMAND hook across every entry. An event may legally
        # carry more than one entry and more than one inner hook: Claude Code
        # supports `prompt`/`agent` hooks that run in parallel with ours, and a
        # `matcher` applies per entry, so a scoped native hook is forced into an
        # entry of its own. Those carry no `command` key at all, which is what
        # distinguishes them here. Counting ENTRIES (or reading only
        # `inner_hooks[0]`) misread both arrangements as faults, while missing a
        # real double registration nested inside one entry — Plan 00266.
        commands = _collect_command_hook_commands(event_hooks)

        if len(commands) > 1:
            issues.append(
                f"{json_key} has {len(commands)} daemon command hooks "
                f"(expected 1) — likely duplicate registration"
            )
            continue

        if not commands:
            # Native hooks may sit ALONGSIDE the wrapper but must never replace
            # it: reconcile_settings_hooks is additive per EVENT, so once the
            # event key exists the self-heal will not restore a wrapper it no
            # longer sees, and every handler on that event goes silently dark.
            issues.append(
                f"{json_key} has no daemon command hook — a prompt/agent hook "
                f"must be added alongside the wrapper, never in place of it"
            )
            continue

        # Check that the command ends with the expected script name
        expected_suffix = f"/.claude/hooks/{expected_bash_key}"
        command = commands[0]
        if not command.endswith(expected_suffix):
            issues.append(
                f"{json_key} command does not end with {expected_suffix}: " f"got {command!r}"
            )

    return issues


# ---------------------------------------------------------------------------
# SSoT-derived reconciliation (merge, not clobber)
# ---------------------------------------------------------------------------
# The reconciler ADDS every missing wired hook registration to a settings dict
# while preserving everything else. It is the single callable shared by the
# session-time self-heal (hook_registration_checker) and the install/upgrade
# merge (Plan 00176). The command shape mirrors install.py's post-Plan-00102
# ``bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/<bash_key>`` form so the exec bit on
# the forwarder is irrelevant. Command-SHAPE fixes for already-present events
# stay the responsibility of ``migrate_settings_to_bash_invocation`` — the
# reconciler only fills in MISSING events, never rewrites present ones.

_HOOK_COMMAND_TYPE = "command"
# The dict KEY that marks an inner hook as a shell-command registration. Shares
# its spelling with _HOOK_COMMAND_TYPE but is a different concept: native
# `prompt`/`agent` hooks have a `type` and no `command` key at all, and that
# absence is how they are told apart from a daemon registration.
_HOOK_COMMAND_KEY = "command"
_HOOK_COMMAND_TEMPLATE = 'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/{bash_key}'
_DEFAULT_HOOK_TIMEOUT_SECONDS = 60
# PreToolUse / PostToolUse carry an explicit per-invocation timeout; all other
# forwarders use Claude Code's default. Kept in lockstep with install.py's
# ``_HOOKS_WITH_TIMEOUT`` via the shared EventID bash_keys.
_BASH_KEYS_WITH_TIMEOUT = frozenset({EventID.PRE_TOOL_USE.bash_key, EventID.POST_TOOL_USE.bash_key})


@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of a settings.json hook reconciliation pass.

    Attributes:
        changed: True iff one or more missing registrations were added.
        events_added: Sorted json_keys of the events that were added (empty
            when ``changed`` is False).
    """

    changed: bool
    events_added: list[str] = field(default_factory=list)


def _build_hook_registration(bash_key: str) -> list[dict[str, Any]]:
    """Build the settings.json ``hooks[event]`` value for a single forwarder."""
    command: dict[str, Any] = {
        "type": _HOOK_COMMAND_TYPE,
        "command": _HOOK_COMMAND_TEMPLATE.format(bash_key=bash_key),
    }
    if bash_key in _BASH_KEYS_WITH_TIMEOUT:
        command["timeout"] = _DEFAULT_HOOK_TIMEOUT_SECONDS
    return [{"hooks": [command]}]


def reconcile_settings_hooks(
    settings: dict[str, Any],
) -> tuple[dict[str, Any], ReconcileResult]:
    """Return a new settings dict with every missing wired hook registered.

    Pure function — the input ``settings`` is never mutated. The full wired
    hook set is derived from the SSoT (``HOOK_EVENTS_IN_SETTINGS`` /
    ``wired_event_metas()``); StatusLine is excluded (top-level key). Present
    events — including any client-added custom entries — are left untouched, and
    all non-``hooks`` top-level keys (``permissions``/``env``/``statusLine``/…)
    are preserved. A malformed (non-dict) ``hooks`` value is replaced with a
    fresh, fully-wired block rather than crashing.

    Args:
        settings: Parsed contents of a settings.json (may be empty/partial).

    Returns:
        ``(new_settings, ReconcileResult)`` where ``new_settings`` is a shallow
        copy with missing registrations added.
    """
    new_settings = dict(settings)

    existing_hooks = new_settings.get("hooks")
    new_hooks: dict[str, Any] = dict(existing_hooks) if isinstance(existing_hooks, dict) else {}

    events_added: list[str] = []
    for json_key in sorted(HOOK_EVENTS_IN_SETTINGS.keys()):
        if json_key in new_hooks:
            continue
        new_hooks[json_key] = _build_hook_registration(HOOK_EVENTS_IN_SETTINGS[json_key])
        events_added.append(json_key)

    new_settings["hooks"] = new_hooks
    return new_settings, ReconcileResult(changed=bool(events_added), events_added=events_added)
