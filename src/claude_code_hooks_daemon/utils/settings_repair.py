"""File-level self-heal for settings.json hook registrations.

Plan 00185 Phase 2. Reads a ``settings.json``, adds every MISSING wired hook
registration via the SSoT-derived :func:`reconcile_settings_hooks`, writes a
one-shot backup, and persists the merged result. This is what lets an
already-installed project stop the SessionStart "Missing hook registration for
{Event}" flood on its NEXT session — without a reinstall or upgrade.

Design (mirrors :mod:`hook_command_migration`):

- **Additive & idempotent.** Only missing events are added; present events
  (including client-added custom entries) are never rewritten. A second run on
  an already-complete file is a no-op — no write, no backup.
- **One-shot backup.** A single ``settings.json.bak.pre-registration-repair`` is
  written before the rewrite and never overwritten if it already exists.
- **Fail-safe.** A non-existent / unreadable / malformed / unwritable
  ``settings.json`` returns ``repaired=False`` rather than crashing session
  start. Session-start handlers must never raise on a broken client file.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from claude_code_hooks_daemon.utils.hook_registration import reconcile_settings_hooks

logger = logging.getLogger(__name__)

# The suffix appended to ``settings.json`` for the one-shot backup.
BACKUP_SUFFIX = ".bak.pre-registration-repair"

# The suffix for the transient staging file used by the atomic write (temp +
# os.replace). It is renamed into place on success and unlinked on failure.
_TMP_SUFFIX = ".tmp.registration-repair"


@dataclass(frozen=True)
class RepairResult:
    """Outcome of a registration-repair pass.

    Attributes:
        repaired: True iff one or more missing registrations were written.
        events_added: Sorted json_keys added (empty when ``repaired`` is False).
        backup_path: Path to the one-shot backup created this pass, or None when
            no repair occurred or a backup already existed.
    """

    repaired: bool
    events_added: list[str] = field(default_factory=list)
    backup_path: Path | None = None


def repair_settings_registrations(settings_path: Path) -> RepairResult:
    """Add missing wired hook registrations to ``settings_path`` in place.

    Side effects occur only when a repair is actually required (at least one
    wired event was missing):

    - A one-shot backup at ``settings_path.name + BACKUP_SUFFIX`` is created from
      the original bytes (never overwritten if it already exists).
    - ``settings_path`` is rewritten with the reconciled JSON.

    Args:
        settings_path: Path to the client's ``settings.json``.

    Returns:
        A :class:`RepairResult` describing what changed (fail-safe: any read /
        parse / write error yields ``repaired=False``).
    """
    if not settings_path.exists():
        return RepairResult(repaired=False)

    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.debug("registration repair skipped — cannot read %s: %s", settings_path, exc)
        return RepairResult(repaired=False)

    if not isinstance(settings, dict):
        return RepairResult(repaired=False)

    new_settings, reconcile_result = reconcile_settings_hooks(settings)
    if not reconcile_result.changed:
        return RepairResult(repaired=False)

    backup_path = settings_path.with_name(settings_path.name + BACKUP_SUFFIX)
    tmp_path = settings_path.with_name(settings_path.name + _TMP_SUFFIX)
    backup_created: Path | None = None
    try:
        if not backup_path.exists():
            # copy2 preserves mtime/permissions and copies the exact bytes.
            shutil.copy2(settings_path, backup_path)
            backup_created = backup_path
        # Atomic write: stage the merged JSON in a sibling temp file, then rename
        # it into place. os.replace is atomic on the same filesystem, so a crash
        # mid-write can never leave settings.json truncated — readers see either
        # the old file or the fully-merged one, never a partial. A failed replace
        # leaves the temp behind (harmless — the next repair overwrites it before
        # its own replace); mirrors utils.retention's atomic-trim pattern.
        tmp_path.write_text(json.dumps(new_settings, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, settings_path)
    except OSError as exc:
        logger.warning("settings registration repair aborted for %s: %s", settings_path, exc)
        return RepairResult(repaired=False)

    return RepairResult(
        repaired=True,
        events_added=reconcile_result.events_added,
        backup_path=backup_created,
    )
