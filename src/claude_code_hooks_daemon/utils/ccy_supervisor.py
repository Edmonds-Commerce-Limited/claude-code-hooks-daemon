"""Shared ccy-supervisor liveness and arming helpers (Plan 00283).

Pure functions extracted from ``ccy_supervisor_integrity`` so that the
SessionStart integrity handler and the ``standing_authorisations`` channel
router share ONE implementation of "is a ccy supervisor armed and live for this
project", rather than each carrying a divergent copy.

The supervisor status file is GLOBAL — one per project root, written once at
launch, carrying no session id and no explicit ``armed`` flag (see
``read_supervisor_status``). So ``armed_supervisor_live`` answers a
PROJECT-scoped question, and "armed" is answered from ``ccy.env`` config rather
than from the status file (Plan 00283 Technical Decision 3): config-armed AND a
live process AND the recorded source fingerprint current.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

_CCY_DIR_PARTS: Final[tuple[str, str]] = (".claude", "ccy")
_CCY_ENV_NAME: Final[str] = "ccy.env"
_SUPERVISOR_SCRIPT_NAME: Final[str] = "claude-supervise.py"
_WRAPPER_EXPORT_KEY: Final[str] = "CCY_CLAUDE_WRAPPER"
_COMMENT_PREFIX: Final[str] = "#"

# Untracked runtime dir relative to the project root, per install mode. Mirrors
# ProjectContext.daemon_untracked_dir() and the supervisor's own resolver so all
# three agree on where the status file lives, without importing ProjectContext
# (callers may pass a fallback cwd root).
_SELF_INSTALL_MARKER_PARTS: Final[tuple[str, str]] = ("src", "claude_code_hooks_daemon")
_SELF_INSTALL_UNTRACKED_PARTS: Final[tuple[str, ...]] = ("untracked",)
_NORMAL_UNTRACKED_PARTS: Final[tuple[str, ...]] = (".claude", "hooks-daemon", "untracked")

_SUPERVISE_SUBDIR: Final[str] = "supervise"
_SUPERVISOR_STATUS_FILENAME: Final[str] = "supervisor-status.json"
# Length of the sha256 hex prefix used as the source fingerprint. MUST match the
# supervisor's compute_source_hash (claude-supervise.py) or every launch reads
# as stale. Cross-process contract; the algorithm is trivial and stable.
_SOURCE_HASH_HEX_LEN: Final[int] = 12

_STATUS_KEY_PID: Final[str] = "pid"
_STATUS_KEY_SOURCE_HASH: Final[str] = "source_hash"


def ccy_dir(project_root: Path) -> Path:
    """Resolve the ``.claude/ccy`` directory under ``project_root``."""
    return project_root.joinpath(*_CCY_DIR_PARTS)


def is_armed(ccy_env: Path) -> bool:
    """Armed = a non-comment line exports the wrapper referencing the script."""
    if not ccy_env.is_file():
        return False
    try:
        content = ccy_env.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.debug("Could not read %s: %s", ccy_env, exc)
        return False
    for raw in content.splitlines():
        stripped = raw.strip()
        if stripped.startswith(_COMMENT_PREFIX):
            continue
        if _WRAPPER_EXPORT_KEY in stripped and _SUPERVISOR_SCRIPT_NAME in stripped:
            return True
    return False


def daemon_untracked_dir(project_root: Path) -> Path:
    """Resolve the daemon untracked dir (install-mode-aware) from the root."""
    if project_root.joinpath(*_SELF_INSTALL_MARKER_PARTS).exists():
        return project_root.joinpath(*_SELF_INSTALL_UNTRACKED_PARTS)
    return project_root.joinpath(*_NORMAL_UNTRACKED_PARTS)


def hash_supervisor_source(path: Path) -> str:
    """Short sha256 fingerprint of ``path`` — MUST match the supervisor's."""
    digest = hashlib.sha256(path.read_bytes(), usedforsecurity=False)
    return digest.hexdigest()[:_SOURCE_HASH_HEX_LEN]


def pid_alive(pid: object) -> bool:
    """Return True iff ``pid`` is a live process we can see.

    ``os.kill(pid, 0)`` raises ESRCH when the process is gone and EPERM when it
    exists but is owned by another user (still alive). Non-int / invalid pids
    are treated as not-alive.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError) as exc:
        # OverflowError: the status file is external JSON, so a corrupt or
        # oversized pid must be treated as not-alive, never crash the caller.
        logger.debug("pid liveness check failed for %s: %s", pid, exc)
        return False
    return True


def read_supervisor_status(project_root: Path) -> dict[str, Any]:
    """Read the running supervisor's status file.

    Returns an EMPTY dict when the file is absent or unreadable/invalid — a
    typed default the caller treats as "no supervisor advertised" (an empty dict
    is falsy), rather than conflating absence with an error via None.
    """
    status_path = (
        daemon_untracked_dir(project_root) / _SUPERVISE_SUBDIR / _SUPERVISOR_STATUS_FILENAME
    )
    if not status_path.is_file():
        return {}
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("Could not read supervisor status %s: %s", status_path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def armed_supervisor_live(project_root: Path) -> bool:
    """True when a ccy supervisor is config-armed AND live AND source-current.

    All three must hold (Plan 00283 Technical Decision 3): "armed" from
    ``ccy.env``, "live" from the recorded pid being a running process, and
    "current" from the recorded source fingerprint matching the on-disk script.
    Answers a PROJECT-scoped question — the status file is global, so this
    cannot distinguish "this session's supervisor" from another session's in a
    shared checkout; the residual edge is documented in the plan.
    """
    supervisor_dir = ccy_dir(project_root)
    if not is_armed(supervisor_dir / _CCY_ENV_NAME):
        return False
    script = supervisor_dir / _SUPERVISOR_SCRIPT_NAME
    if not script.is_file():
        return False
    status = read_supervisor_status(project_root)
    if not status:
        return False
    if not pid_alive(status.get(_STATUS_KEY_PID)):
        return False
    running_hash = status.get(_STATUS_KEY_SOURCE_HASH)
    if not isinstance(running_hash, str) or not running_hash:
        return False
    try:
        ondisk_hash = hash_supervisor_source(script)
    except OSError as exc:
        logger.debug("Could not hash supervisor source %s: %s", script, exc)
        return False
    return running_hash == ondisk_hash
