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
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Public: the suffix appended to ``settings.json`` for the one-shot backup.
BACKUP_SUFFIX = ".bak.pre-bash-migration"

# Daemon-wrapper bare-path commands look like:
#   "$CLAUDE_PROJECT_DIR"/.claude/hooks/<bash-key>
# A migrated command starts with ``bash `` (note the trailing space).
_BASH_PREFIX = "bash "
_DAEMON_WRAPPER_FRAGMENT = "/.claude/hooks/"

# A legacy command must look like a daemon wrapper AND not already be
# wrapped in ``bash ``. We check via simple string operations rather than
# a regex — the shape is anchored enough that a regex would obscure intent.
_LEGACY_PATH_PATTERN = re.compile(
    r'^"?\$\{?CLAUDE_PROJECT_DIR\}?"?/\.claude/hooks/[a-z][a-z0-9-]*$'
)


def is_legacy_hook_command(command: str) -> bool:
    """Return True iff ``command`` is a bare daemon-wrapper path needing migration.

    A command qualifies as legacy when it points at the daemon wrapper
    directory using the standard ``$CLAUDE_PROJECT_DIR`` form, has no
    ``bash`` (or other interpreter) prefix, and has no extra arguments.
    Any other shape — custom user script, already-wrapped command, empty
    string — returns False so we never touch hand-rolled config.
    """
    if not command:
        return False
    if command.startswith(_BASH_PREFIX):
        return False
    if _DAEMON_WRAPPER_FRAGMENT not in command:
        return False
    return _LEGACY_PATH_PATTERN.match(command.strip()) is not None


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
                if isinstance(command, str) and is_legacy_hook_command(command):
                    new_command_entry = dict(command_entry)
                    new_command_entry["command"] = _BASH_PREFIX + command
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
    if not isinstance(hooks_block, dict):
        return MigrationResult(migrated=False)

    new_hooks_block, events_migrated = _migrate_hooks_block(hooks_block)
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
    new_settings["hooks"] = new_hooks_block
    settings_path.write_text(json.dumps(new_settings, indent=2) + "\n", encoding="utf-8")

    return MigrationResult(
        migrated=True,
        events_migrated=events_migrated,
        backup_path=backup_created,
    )
