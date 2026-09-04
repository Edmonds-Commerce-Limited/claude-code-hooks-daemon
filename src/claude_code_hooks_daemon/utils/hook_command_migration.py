"""Bare-path → ``bash <path>`` settings.json migrator.

Plan 00102 Phase 2 (Tier 2). When an existing client repo upgrades to a
daemon version that emits hooks via ``bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/<event>``,
this utility rewrites the legacy bare-path entries one time per repo so
that hook execution survives the executable-bit being dropped.

Design choices:

- **One-shot backup.** A single ``settings.json.bak.pre-bash-migration``
  is written before the rewrite. If a backup already exists from an
  earlier (possibly aborted) migration attempt, it is **never** overwritten —
  the user's original settings are sacred.
- **Idempotent.** Running migration on an already-migrated file is a
  no-op: no rewrite, no backup, no events reported.
- **Targeted.** Only commands that match the daemon-wrapper bare-path
  shape are rewritten. Hand-edited custom scripts and ``bash`` invocations
  with extra args are left strictly alone.
- **Rebuilt, not prefixed.** A legacy command is re-rendered from the shared
  ``HOOK_COMMAND_TEMPLATE`` using its wrapper basename. Prefixing would leave
  a RELATIVE legacy path resolving against the process cwd — fixing the exec
  bit while leaving the working-directory half of the defect in place.

Scope covers the top-level ``statusLine`` key as well as ``settings["hooks"]``.
Both are shell commands invoked the same way, and covering only the latter
left the status line as the one registration no upgrade could repair
(Plan 00102 Phase 6).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.utils.hook_registration import (
    BASH_INVOCATION_PREFIX,
    HOOK_COMMAND_TEMPLATE,
)

logger = logging.getLogger(__name__)

# Public: the suffix appended to ``settings.json`` for the one-shot backup.
BACKUP_SUFFIX = ".bak.pre-bash-migration"

# Daemon-wrapper bare-path commands look like:
#   "$CLAUDE_PROJECT_DIR"/.claude/hooks/<bash-key>
# A migrated command starts with ``bash `` (note the trailing space).
_BASH_PREFIX = BASH_INVOCATION_PREFIX
_WRAPPER_DIR_FRAGMENT = ".claude/hooks/"

# The top-level settings key the status line registers under. It sits OUTSIDE
# ``settings["hooks"]``, which is the whole reason it needs naming here: the
# migrator's walk covered the hooks block only, so an upgraded client kept a
# bare status-line command indefinitely (Plan 00102 Phase 6).
_STATUS_LINE_KEY = "statusLine"

# Two legacy shapes, both capturing the bash_key so the command can be
# REBUILT rather than merely prefixed.
#
# The anchored form is what a pre-Phase-1 `install.py` wrote. The RELATIVE
# form is what `scripts/install_version.sh`'s fallback wrote, and excluding it
# was a silent hole: that fallback's output is the one install shape nothing
# else repairs, because `reconcile_settings_hooks` only ADDS missing events
# and never rewrites present ones.
_ANCHORED_PATH_PATTERN = re.compile(
    r'^"?\$\{?CLAUDE_PROJECT_DIR\}?"?/\.claude/hooks/([a-z][a-z0-9-]*)$'
)
_RELATIVE_PATH_PATTERN = re.compile(r"^\.{0,2}/?\.claude/hooks/([a-z][a-z0-9-]*)$")


def legacy_command_bash_key(command: str) -> str | None:
    """Return the wrapper basename if ``command`` is a legacy bare path, else None.

    A command qualifies as legacy when it points at the daemon wrapper
    directory, has no ``bash`` (or other interpreter) prefix, and has no extra
    arguments. Any other shape — custom user script, already-wrapped command,
    empty string — returns None so we never touch hand-rolled config.

    Returns the KEY rather than a bool because a relative legacy command
    cannot be fixed by prefixing: ``bash .claude/hooks/x`` still resolves
    against the process cwd. Only the key lets the canonical, anchored command
    be rebuilt.
    """
    if not command:
        return None
    if command.startswith(_BASH_PREFIX):
        return None
    if _WRAPPER_DIR_FRAGMENT not in command:
        return None
    stripped = command.strip()
    for pattern in (_ANCHORED_PATH_PATTERN, _RELATIVE_PATH_PATTERN):
        match = pattern.match(stripped)
        if match is not None:
            return match.group(1)
    return None


def canonical_hook_command(bash_key: str) -> str:
    """The one command shape every source must emit, rendered from the SSoT."""
    return HOOK_COMMAND_TEMPLATE.format(bash_key=bash_key)


def is_legacy_hook_command(command: str) -> bool:
    """Whether ``command`` is a bare daemon-wrapper path needing migration."""
    return legacy_command_bash_key(command) is not None


@dataclass(frozen=True)
class MigrationResult:
    """Outcome of a migration pass.

    Attributes:
        migrated: True iff one or more commands were rewritten on disk.
        events_migrated: Sorted list of event keys whose commands were
            rewritten (e.g. ``["PreToolUse", "PostToolUse"]``). Empty when
            ``migrated`` is False.
        backup_path: Path to the one-shot backup if one was created during
            this pass. None when no migration occurred or when an
            existing backup was preserved.
    """

    migrated: bool
    events_migrated: list[str] = field(default_factory=list)
    backup_path: Path | None = None


def _migrate_hooks_block(
    hooks_block: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Return a new hooks block plus the sorted list of migrated event keys.

    The input is left unmodified. This is a pure function — caller decides
    whether and where to write the result.
    """
    migrated_events: list[str] = []
    new_block: dict[str, Any] = {}
    for event_key, event_value in hooks_block.items():
        if not isinstance(event_value, list):
            new_block[event_key] = event_value
            continue
        new_event_value: list[Any] = []
        event_was_migrated = False
        for hook_entry in event_value:
            if not isinstance(hook_entry, dict):
                new_event_value.append(hook_entry)
                continue
            inner_hooks = hook_entry.get("hooks")
            if not isinstance(inner_hooks, list):
                new_event_value.append(hook_entry)
                continue
            new_inner: list[Any] = []
            for command_entry in inner_hooks:
                if not isinstance(command_entry, dict):
                    new_inner.append(command_entry)
                    continue
                command = command_entry.get("command", "")
                bash_key = legacy_command_bash_key(command) if isinstance(command, str) else None
                if bash_key is not None:
                    new_command_entry = dict(command_entry)
                    # Rebuilt from the key, not prefixed. A relative legacy
                    # command prefixed with `bash ` would still resolve
                    # against the process cwd — a migration reporting success
                    # having fixed only half the defect.
                    new_command_entry["command"] = canonical_hook_command(bash_key)
                    new_inner.append(new_command_entry)
                    event_was_migrated = True
                else:
                    new_inner.append(command_entry)
            new_hook_entry = dict(hook_entry)
            new_hook_entry["hooks"] = new_inner
            new_event_value.append(new_hook_entry)
        new_block[event_key] = new_event_value
        if event_was_migrated:
            migrated_events.append(event_key)
    return new_block, sorted(migrated_events)


def _migrate_status_line(settings: dict[str, Any]) -> dict[str, Any] | None:
    """Return a repaired ``statusLine`` block, or None when nothing to do.

    Every other key in the block is carried over — ``refreshInterval`` is
    load-bearing (Plan 00175: without it the clock stalls and the multithread
    indicator under-counts), so rebuilding the block from scratch would
    silently degrade the status line while "fixing" it.
    """
    status_line = settings.get(_STATUS_LINE_KEY)
    if not isinstance(status_line, dict):
        return None
    command = status_line.get("command")
    if not isinstance(command, str):
        return None
    bash_key = legacy_command_bash_key(command)
    if bash_key is None:
        return None
    repaired = dict(status_line)
    repaired["command"] = canonical_hook_command(bash_key)
    return repaired


def migrate_settings_to_bash_invocation(settings_path: Path) -> MigrationResult:
    """Migrate ``settings_path`` in place from bare-path to ``bash <path>``.

    Side effects only when migration is required:

    - A one-shot backup at ``settings_path.with_name(name + BACKUP_SUFFIX)``
      is created from the original on-disk bytes (never overwritten if it
      already exists from an earlier attempt).
    - ``settings_path`` is rewritten with the migrated JSON.

    A non-existent ``settings_path`` is treated as a no-op rather than an
    error — fresh installs and projects without hooks daemon configured
    must not crash on session start.
    """
    if not settings_path.exists():
        return MigrationResult(migrated=False)

    try:
        original_text = settings_path.read_text(encoding="utf-8")
        settings = json.loads(original_text)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.debug("hook command migration skipped — cannot read %s: %s", settings_path, exc)
        return MigrationResult(migrated=False)

    if not isinstance(settings, dict):
        return MigrationResult(migrated=False)

    hooks_block = settings.get("hooks")
    # A malformed or absent hooks block does not end the pass: the status line
    # lives under its own top-level key, so it stays repairable regardless.
    new_hooks_block, events_migrated = (
        _migrate_hooks_block(hooks_block) if isinstance(hooks_block, dict) else (None, [])
    )
    new_status_line = _migrate_status_line(settings)
    if new_status_line is not None:
        events_migrated = sorted([*events_migrated, _STATUS_LINE_KEY])

    if not events_migrated:
        return MigrationResult(migrated=False)

    backup_path = settings_path.with_name(settings_path.name + BACKUP_SUFFIX)
    backup_created: Path | None = None
    if not backup_path.exists():
        # ``copy2`` preserves mtime/permissions and writes from disk to
        # disk — guaranteed to capture exactly the original bytes.
        shutil.copy2(settings_path, backup_path)
        backup_created = backup_path

    new_settings = dict(settings)
    if new_hooks_block is not None:
        new_settings["hooks"] = new_hooks_block
    if new_status_line is not None:
        new_settings[_STATUS_LINE_KEY] = new_status_line
    settings_path.write_text(json.dumps(new_settings, indent=2) + "\n", encoding="utf-8")

    return MigrationResult(
        migrated=True,
        events_migrated=events_migrated,
        backup_path=backup_created,
    )
