"""Content fingerprint of the code a running daemon actually loaded (Plan 00371).

A ``DaemonController`` imports every handler module -- built-in and
project-level -- exactly once, at ``initialise()`` time, and never
hot-reloads them: a source edit on disk after that point has no effect on
the running process until it is restarted. Plan 00371's field incident was
exactly this -- the acceptance harness dispatched a probe through the live
daemon socket, the running daemon still held pre-merge code, and the probe
failed for a reason nothing in the harness could name, because nothing
compared what the daemon had loaded against what was on disk.

This module is the mechanical half of the fix: a deterministic content hash
of the ``.py`` files a daemon process would import, given the same roots. It
knows nothing about sockets or config loading -- callers gather the roots
(``daemon/controller.py`` already has them resolved from its own startup
parameters; a QA-side caller resolves them independently) and pass them in.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: Two levels up from this file (``daemon/source_fingerprint.py``) is the
#: package root (``claude_code_hooks_daemon/``) -- wherever the running
#: interpreter actually resolved this module from. Correct in both
#: self-install mode (this repository's own ``src/``) and a client install
#: (the deployed copy under ``.claude/hooks-daemon/src/``), because it names
#: the location THIS import came from rather than guessing a layout.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def daemon_package_root() -> Path:
    """Return the directory the running interpreter imported this package from."""
    return _PACKAGE_ROOT


def compute_source_fingerprint(*roots: Path) -> str:
    """Return a sha256 hex digest summarising every ``.py`` file under ``roots``.

    Deterministic regardless of filesystem iteration order (files are
    visited in sorted path order) and sensitive to both a content change and
    a rename (each file's path relative to its root is mixed in alongside
    its bytes, so moving a handler to a different event-type directory
    changes the digest even though the bytes did not).

    A root that does not exist is skipped rather than raising -- matching
    the project convention that an optional directory's absence (e.g. no
    project-handlers tree yet) is a normal state, not a fatal one. Only
    ``.py`` files are hashed: the fingerprint's contract is "the code a
    running Python process imported", not "everything under this path".
    """
    hasher = hashlib.sha256(usedforsecurity=False)
    for root in roots:
        if not root.is_dir():
            continue
        for py_file in sorted(root.rglob("*.py")):
            if not py_file.is_file():
                continue
            hasher.update(str(py_file.relative_to(root)).encode("utf-8"))
            hasher.update(py_file.read_bytes())
    return hasher.hexdigest()


def compute_daemon_identity_fingerprint(*extra_roots: Path) -> str:
    """Fingerprint of the daemon's own package plus any caller-supplied extra roots.

    ``extra_roots`` is typically a single resolved project-handlers
    directory (only when project handlers are enabled -- the caller decides
    that; this function has no config awareness). Passing none reduces to
    the fingerprint of the daemon package alone.
    """
    return compute_source_fingerprint(daemon_package_root(), *extra_roots)


def compute_current_project_fingerprint(project_root: Path | str) -> str:
    """Fingerprint of the code a daemon freshly started against ``project_root`` would load.

    Loads the project's own ``hooks-daemon.yaml`` (falling back to defaults
    when absent or malformed -- a freshness CHECK must not itself crash on an
    already-broken config, which is a separate, already-surfaced problem) to
    resolve ``project_handlers`` exactly the way
    ``DaemonController.initialise()`` does, so a caller with no live
    controller instance -- a CLI verb, an acceptance test -- computes the
    SAME value a running daemon reports, rather than assuming the default
    layout.
    """
    from pydantic import ValidationError

    from claude_code_hooks_daemon.config.models import Config
    from claude_code_hooks_daemon.utils.repo_relative_path import (
        resolve_repo_relative_path,
    )

    project_root = Path(project_root)
    try:
        config = Config.find_and_load(project_root)
    except (FileNotFoundError, ValidationError) as exc:
        logger.warning(
            "Could not load config at %s for freshness check, using defaults: %s",
            project_root,
            exc,
        )
        config = Config()

    extra_roots: list[Path] = []
    if config.project_handlers.enabled:
        extra_roots.append(
            resolve_repo_relative_path(config.project_handlers.path, project_root)
        )
    return compute_daemon_identity_fingerprint(*extra_roots)


def describe_fingerprint_mismatch(running_fingerprint: str | None, current_fingerprint: str) -> str | None:
    """Return a diagnostic message if the running daemon looks stale, else ``None``.

    ``running_fingerprint`` is what a live daemon reported over its
    ``_system``/``health`` socket action; ``current_fingerprint`` is freshly
    computed from the on-disk source. ``None`` for ``running_fingerprint``
    covers every case where nothing trustworthy was reported -- the daemon
    did not respond, or its health payload carried no fingerprint at all (a
    daemon predating this plan, or a legacy-controller fallback health
    dict) -- and is treated as a staleness RISK rather than "cannot tell",
    because a caller that can't verify freshness must not silently trust a
    live-dispatch result either.
    """
    if running_fingerprint is None:
        return (
            "Could not verify the running daemon's loaded source matches the "
            "working tree (no source_fingerprint in its health response -- "
            "the daemon may be down, unreachable, or predates Plan 00371). "
            "Restart it with `bin/hooks-daemon restart` and retry."
        )
    if running_fingerprint != current_fingerprint:
        return (
            f"STALE DAEMON: the running daemon's loaded code "
            f"(source_fingerprint {running_fingerprint[:12]}) does not match "
            f"the current working tree (source_fingerprint "
            f"{current_fingerprint[:12]}). A live-dispatch result graded "
            f"against it would be judging the OLD code, not what's on disk. "
            f"Restart it with `bin/hooks-daemon restart` and retry."
        )
    return None
