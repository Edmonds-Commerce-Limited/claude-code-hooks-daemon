"""The daemon-owned permission-prompt surface of ``settings.json`` (Plan 00474).

Claude Code keeps its critical-path removal prompt switched on, even in a
bypass-permissions session, whenever a ``PermissionRequest`` hook of any matcher
is registered or a deny rule targets Bash, Edit or Read. See the vendored
``remote-docs/code.claude.com/docs/en/permission-modes.md``, section "Why the
critical-path removal prompt stays on". The daemon ships both, so a session
that runs in bypass mode still gets that prompt.

``daemon.omit_permission_surface: true`` in ``.claude/hooks-daemon.yaml`` is the
opt-in way out: the daemon then registers no ``PermissionRequest`` forwarder and
writes no ``permissions.deny`` rules, and relies on its PreToolUse handlers
instead. This module is the single definition of WHAT those entries are, shared
by the project-settings writer, the validators and the ``permission-surface``
CLI verb, so none of them can drift.

Ownership: only entries the daemon wrote are ever touched. A user's own deny
rule, other ``permissions`` keys, and any hook of theirs in the same event stay.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, Final

import yaml

from claude_code_hooks_daemon.config.yaml_loading import safe_load_yaml
from claude_code_hooks_daemon.constants.events import EventID
from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.hook_command_migration import (
    canonical_hook_command,
    legacy_command_bash_key,
)
from claude_code_hooks_daemon.utils.hook_registration import build_hook_registration

logger = logging.getLogger(__name__)

#: Key under ``daemon:`` in ``.claude/hooks-daemon.yaml``.
OMIT_KEY: Final = "omit_permission_surface"

#: Project config file name, beside ``settings.json`` in ``.claude/``.
CONFIG_FILE_NAME: Final = "hooks-daemon.yaml"

PERMISSION_REQUEST_EVENT: Final = EventID.PERMISSION_REQUEST.json_key
_PERMISSION_REQUEST_BASH_KEY: Final = EventID.PERMISSION_REQUEST.bash_key
_PERMISSION_REQUEST_COMMAND: Final = canonical_hook_command(_PERMISSION_REQUEST_BASH_KEY)

#: Label reported for a removed hook registration.
HOOK_LABEL: Final = f"hooks.{PERMISSION_REQUEST_EVENT}"


def daemon_deny_rules() -> tuple[str, ...]:
    """The ``permissions.deny`` rules the daemon writes, one per ephemeral root."""
    return tuple(ProjectPath.claude_code_deny_rule(root) for root in ProjectPath.EPHEMERAL_ROOTS)


def daemon_permission_surface() -> dict[str, Any]:
    """The exact settings fragment the switch removes from a project.

    Built from the same generators the project-settings template is checked
    against, so a user-level copy of it matches what the writer emits.
    """
    return {
        "permissions": {"deny": list(daemon_deny_rules())},
        "hooks": {PERMISSION_REQUEST_EVENT: build_hook_registration(_PERMISSION_REQUEST_BASH_KEY)},
    }


def read_omit_permission_surface(settings_path: Path) -> bool:
    """Whether the project beside ``settings_path`` opted in to omitting the surface.

    Reads ``hooks-daemon.yaml`` from the same directory. Absent config or an
    absent key is off, which is the default. A config that cannot be read or
    carries a non-boolean value is also treated as off, and is logged at
    WARNING: the default keeps the protections, which is the safe direction.
    """
    return read_permission_surface_setting(settings_path) is SwitchSetting.ON


class SwitchSetting(Enum):
    """What ``daemon.omit_permission_surface`` says in a project's config."""

    #: No config file, or the key is not set. Nothing was asked for.
    ABSENT = "absent"
    #: ``true``: omit the daemon-owned permission surface.
    ON = "on"
    #: An explicit ``false``: the user switched the option back off.
    OFF = "off"
    #: The config exists but could not be read, or the value is not a boolean.
    UNREADABLE = "unreadable"


def read_permission_surface_setting(settings_path: Path) -> SwitchSetting:
    """The switch as written, with an unreadable config as its own value.

    The merge needs the difference between "absent" and "explicitly false": only
    an explicit ``false`` (the user switching the option back off) restores deny
    rules the daemon removed earlier. An absent key leaves a client's
    ``permissions`` exactly as it was, so a config without the key behaves as it
    did before the switch existed. An unreadable or malformed config is
    ``UNREADABLE``, logged once at WARNING, and is not ``OFF``: it must not
    restore anything, nor omit anything.
    """
    config_path = settings_path.parent / CONFIG_FILE_NAME
    if not config_path.is_file():
        return SwitchSetting.ABSENT
    try:
        with config_path.open(encoding="utf-8") as stream:
            document = safe_load_yaml(stream)
        return _switch_from_document(document)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        log_and_continue(
            logger,
            exc,
            reason=(
                f"{config_path} could not be read for daemon.{OMIT_KEY}, so the "
                "switch is treated as off and the permission surface is kept"
            ),
        )
        return SwitchSetting.UNREADABLE


def _switch_from_document(document: Any) -> SwitchSetting:
    """Extract ``daemon.omit_permission_surface``; raise ValueError if malformed."""
    if document is None:
        return SwitchSetting.ABSENT
    if not isinstance(document, dict):
        raise ValueError("configuration is not a mapping")
    daemon = document.get("daemon")
    if daemon is None:
        return SwitchSetting.ABSENT
    if not isinstance(daemon, dict):
        raise ValueError("`daemon` is not a mapping")
    value = daemon.get(OMIT_KEY)
    if value is None:
        return SwitchSetting.ABSENT
    if not isinstance(value, bool):
        raise ValueError(f"daemon.{OMIT_KEY} must be true or false, got {value!r}")
    return SwitchSetting.ON if value else SwitchSetting.OFF


def _is_daemon_forwarder(inner: Any) -> bool:
    if not isinstance(inner, dict):
        return False
    command = inner.get("command")
    if not isinstance(command, str):
        return False
    return (
        command == _PERMISSION_REQUEST_COMMAND
        or legacy_command_bash_key(command) == _PERMISSION_REQUEST_BASH_KEY
    )


def _strip_hook(hooks: dict[str, Any]) -> bool:
    """Remove the daemon forwarder from the PermissionRequest event, in place."""
    groups = hooks.get(PERMISSION_REQUEST_EVENT)
    if not isinstance(groups, list):
        return False
    removed = False
    kept_groups: list[Any] = []
    for group in groups:
        inner_list = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(inner_list, list):
            kept_groups.append(group)
            continue
        kept_inner = [inner for inner in inner_list if not _is_daemon_forwarder(inner)]
        if len(kept_inner) == len(inner_list):
            kept_groups.append(group)
            continue
        removed = True
        if kept_inner:
            kept_groups.append({**group, "hooks": kept_inner})
    if not removed:
        return False
    if kept_groups:
        hooks[PERMISSION_REQUEST_EVENT] = kept_groups
    else:
        del hooks[PERMISSION_REQUEST_EVENT]
    return True


def _strip_deny_rules(permissions: dict[str, Any]) -> tuple[str, ...]:
    """Remove the daemon's deny rules from ``permissions``, in place."""
    deny = permissions.get("deny")
    if not isinstance(deny, list):
        return ()
    owned = set(daemon_deny_rules())
    removed = tuple(rule for rule in deny if isinstance(rule, str) and rule in owned)
    if not removed:
        return ()
    remaining = [rule for rule in deny if not (isinstance(rule, str) and rule in owned)]
    if remaining:
        permissions["deny"] = remaining
    else:
        del permissions["deny"]
    return removed


def restore_deny_rules(settings: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Add the daemon's deny rules that a ``permissions`` block is missing.

    The inverse of the deny half of :func:`strip_permission_surface`, used when
    the switch is off so that turning it off again brings the rules back even
    though the user's ``permissions`` key exists. Only absent daemon rules are
    appended; every user rule and other ``permissions`` key is left exactly as
    it was. A ``permissions`` or ``deny`` value of the wrong type is the user's
    to fix and is left alone. An absent ``permissions`` key is not handled here:
    the merge delivers it whole.

    Pure: ``settings`` is not mutated.

    Returns:
        ``(new_settings, added)`` where ``added`` lists each rule appended.
    """
    new_settings = copy.deepcopy(dict(settings))
    permissions = new_settings.get("permissions")
    if not isinstance(permissions, dict):
        return new_settings, ()
    deny = permissions.get("deny", [])
    if not isinstance(deny, list):
        return new_settings, ()
    present = {rule for rule in deny if isinstance(rule, str)}
    added = tuple(rule for rule in daemon_deny_rules() if rule not in present)
    if added:
        permissions["deny"] = [*deny, *added]
    return new_settings, added


def strip_permission_surface(
    settings: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Remove the daemon-owned permission surface from a settings document.

    Pure: ``settings`` is not mutated.

    Returns:
        ``(new_settings, removed)`` where ``removed`` names each entry taken out
        (``hooks.PermissionRequest`` and each deny rule), empty when there was
        nothing of ours to remove. A ``permissions`` block left empty by the
        removal is dropped; one the user left empty themselves is not touched.
    """
    new_settings = copy.deepcopy(dict(settings))
    removed: list[str] = []

    hooks = new_settings.get("hooks")
    if isinstance(hooks, dict) and _strip_hook(hooks):
        removed.append(HOOK_LABEL)

    permissions = new_settings.get("permissions")
    if isinstance(permissions, dict):
        rules = _strip_deny_rules(permissions)
        removed.extend(rules)
        if rules and not permissions:
            del new_settings["permissions"]

    return new_settings, tuple(removed)
