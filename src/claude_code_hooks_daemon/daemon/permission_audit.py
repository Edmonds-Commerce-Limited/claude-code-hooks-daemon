"""Batch permission audit for the daemon's untracked tree (Plan 00239).

The daemon used to daemonise with ``umask(0)``, so everything it created landed
group- and world-writable. Fixing the umask governs future creates and retro-fixes
NOTHING: every already-deployed daemon keeps its world-writable verdict log,
payload captures and sidecars until something looks at them.

That gap is structural, not an oversight — a write-time guard cannot see what is
already on disk — so the fix needs a batch equivalent that runs against an
existing install. This module is it, and
``hooks-daemon check-permissions [--fix]`` is how it is invoked.

**The rule is group-or-other WRITABLE.** Each exclusion below was measured as a
false positive against a real install rather than anticipated:

* **symlinks** are always ``lrwxrwxrwx``; the mode belongs to the target, and a
  venv's ``bin/python`` and ``lib64`` are symlinks;
* **venv trees** belong to a package manager, and uv leaves a ``0666`` ``.lock``
  inside one;
* the **daemon socket** is deliberately ``0660`` via an explicit post-bind
  ``chmod``, so callers pass it as exempt.

Flagging other-READABLE as well was considered and rejected: nothing the fixed
daemon creates is other-readable, whereas a venv tree is full of legitimate
``0644``, so the rule would be mostly noise. Writable is the unambiguous bug
shape — which is also why the original measurement used ``-perm /022`` and not
``-perm /077``, the latter matching every harmless ``0644``.
"""

from __future__ import annotations

import logging
import stat
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from itertools import chain
from pathlib import Path

logger = logging.getLogger(__name__)

# Group/other WRITE bits — the bug shape this audit exists to find.
_GROUP_OTHER_WRITE = stat.S_IWGRP | stat.S_IWOTH

# All group/other bits, stripped on remediation.
_GROUP_AND_OTHER = stat.S_IRWXG | stat.S_IRWXO

# Directory-name prefix for virtualenvs living under the untracked tree
# (self-install mode keeps them there). Their contents are not daemon artefacts.
_VENV_DIR_PREFIX = "venv"


@dataclass(frozen=True)
class PermissionFinding:
    """One artefact whose mode grants write access beyond its owner."""

    path: Path
    mode: int

    def describe(self) -> str:
        """Human-readable one-liner: ``0666 /path/to/file``."""
        return f"{self.mode:04o} {self.path}"


def _is_in_venv(path: Path, root: Path) -> bool:
    """True when ``path`` sits inside a virtualenv directory under ``root``."""
    return any(part.startswith(_VENV_DIR_PREFIX) for part in path.relative_to(root).parts)


def audit_untracked_permissions(
    untracked_dir: Path,
    *,
    exempt: Collection[Path] = (),
) -> list[PermissionFinding]:
    """Find artefacts under ``untracked_dir`` writable by group or other.

    Args:
        untracked_dir: The daemon's untracked directory. A missing directory is
            not an error — a daemon that has never run has no tree yet.
        exempt: Paths to skip, for artefacts whose permissive mode is deliberate
            (the socket).

    Returns:
        Findings sorted by path, so output is stable and diffable.
    """
    if not untracked_dir.is_dir():
        return []

    exempted = {path.resolve() for path in exempt}
    findings: list[PermissionFinding] = []

    # The ROOT is audited too, not just its contents. `rglob` never yields the
    # directory it is called on, and the root is the single most impactful
    # entry: `umask(0)` created it 0777, and a world-writable directory lets
    # any local user unlink and replace the socket, PID file, verdict log and
    # payload captures inside it however tight those files' own modes are.
    # Omitting it made this command print a clean bill of health for exactly
    # the installs it was written to remediate.
    for path in chain([untracked_dir], untracked_dir.rglob("*")):
        # A symlink's own mode is always 0777 and says nothing about its target,
        # so lstat'ing one only ever produces a false positive.
        if path.is_symlink():
            continue
        if _is_in_venv(path, untracked_dir):
            continue
        try:
            if path.resolve() in exempted:
                continue
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError as exc:
            # Explicit: a vanished or unreadable entry is reported, never hidden.
            logger.warning("permission audit: cannot stat %s: %s", path, exc)
            continue
        if mode & _GROUP_OTHER_WRITE:
            findings.append(PermissionFinding(path=path, mode=mode))

    return sorted(findings, key=lambda finding: finding.path)


def tighten_permissions(findings: Iterable[PermissionFinding]) -> list[Path]:
    """Strip every group and other bit from each finding.

    Owner bits are untouched, so a directory keeps its owner-execute and stays
    traversable — stripping that would brick the tree rather than secure it.

    This is deliberately NOT run automatically at startup: a daemon silently
    rewriting permissions across a user-owned tree is its own risk. It is invoked
    explicitly, by a user who has read what the audit reported.

    Args:
        findings: Findings from :func:`audit_untracked_permissions`.

    Returns:
        The paths actually changed.
    """
    changed: list[Path] = []
    for finding in findings:
        try:
            finding.path.chmod(finding.mode & ~_GROUP_AND_OTHER)
        except OSError as exc:
            logger.warning("permission audit: cannot chmod %s: %s", finding.path, exc)
            continue
        changed.append(finding.path)
    return changed
