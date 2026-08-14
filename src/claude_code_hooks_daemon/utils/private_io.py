"""Owner-only file and directory creation (Plan 00239).

Defence in depth for the three artefacts whose CONTENTS are known-sensitive —
``payload-capture/`` (raw hook payloads, including Write/Edit file bodies), the
verdict log, and the stop-event log. The daemon's ``0o077`` umask
(:data:`~claude_code_hooks_daemon.constants.permissions.FileMode.DAEMON_UMASK`)
already makes every create owner-only; these helpers pass the mode explicitly at
the create site as well, so the guarantee survives someone later "restoring" the
textbook ``umask(0)`` that caused the original defect.

The redundancy is the point: neither layer is load-bearing on its own.

**Scope**: these are WRITE-path helpers, so they govern what the daemon creates
from now on. Neither one re-chmods something already on disk — a daemon silently
rewriting permissions across a user-owned tree is its own risk, and the deliberate
Non-Goal of the plan that added this. Files predating the fix are handled by the
documented upgrade remediation and by the batch permission check, which is what a
write-time guard structurally cannot cover.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TextIO

from claude_code_hooks_daemon.constants.permissions import FileMode


def open_private_append(path: Path) -> TextIO:
    """Open ``path`` for UTF-8 append, creating it owner-only if it is new.

    Args:
        path: File to append to. Its parent must already exist (use
            :func:`make_private_dir`).

    Returns:
        A text-mode append handle, for use as a context manager exactly like
        ``path.open("a", encoding="utf-8")``.

    Raises:
        OSError: If the file cannot be opened. Callers decide how to react —
            never silently swallowed.
    """
    # The mode argument applies ONLY when O_CREAT actually creates the file, so an
    # existing file keeps whatever mode it has. That is intended (see module docs).
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FileMode.PRIVATE_FILE)
    return os.fdopen(descriptor, "a", encoding="utf-8")


def make_private_dir(path: Path) -> None:
    """Create ``path`` and any missing ancestors, each owner-only.

    ``Path.mkdir(parents=True, mode=...)`` applies the mode to the LEAF only —
    intermediate directories are created with the default ``0o777`` masked by the
    umask. Under a cleared umask that leaves a private leaf sitting inside a
    world-writable parent, which is not a meaningful guarantee. This creates each
    missing ancestor explicitly instead.

    Existing directories are left untouched, including their mode.

    Args:
        path: Directory to create.

    Raises:
        OSError: If a directory cannot be created.
    """
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        parent = current.parent
        if parent == current:  # Reached the filesystem root.
            break
        current = parent

    for directory in reversed(missing):
        directory.mkdir(mode=FileMode.PRIVATE_DIR, exist_ok=True)
