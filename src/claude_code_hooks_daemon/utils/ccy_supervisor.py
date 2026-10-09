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
import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.core.relevance import Relevance, RelevanceContext
from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

_CCY_DIR_PARTS: Final[tuple[str, str]] = (".claude", "ccy")
_CCY_ENV_NAME: Final[str] = "ccy.env"
_SUPERVISOR_SCRIPT_NAME: Final[str] = "claude-supervise.py"
# The shell launcher ccy.env's wrapper points at (see install/ccy_supervisor.py).
# It is a prefix of the script name, so one substring test recognises a wrapper
# that names either the launcher or the bare script (a pre-launcher install).
_SUPERVISOR_LAUNCHER_NAME: Final[str] = "claude-supervise"
_WRAPPER_EXPORT_KEY: Final[str] = "CCY_CLAUDE_WRAPPER"
_COMMENT_PREFIX: Final[str] = "#"

_SUPERVISE_SUBDIR: Final[str] = "supervise"
_SUPERVISOR_STATUS_FILENAME: Final[str] = "supervisor-status.json"
# Length of the sha256 hex prefix used as the source fingerprint. MUST match the
# supervisor's compute_source_hash (claude-supervise.py) or every launch reads
# as stale. Cross-process contract; the algorithm is trivial and stable.
_SOURCE_HASH_HEX_LEN: Final[int] = 12

_STATUS_KEY_PID: Final[str] = "pid"
_STATUS_KEY_SOURCE_HASH: Final[str] = "source_hash"

# The supervisor's INVARIANT provenance prefix on every line it types -- matches
# both the goal-injection form (`🤖 [ccy-supervisor] ...`) and the timestamped
# form (`🤖 [ccy-supervisor 2026-08-28 10:51:04] continue`). It deliberately has
# NO closing bracket, mirroring the supervisor's own `_BOT_PREFIX` in
# `.claude/ccy/claude-supervise.py`; a literal `🤖 [ccy-supervisor]` would miss
# every timestamped line.
CCY_SUPERVISOR_MARKER: Final[str] = "🤖 [ccy-supervisor"


def ccy_dir(project_root: Path) -> Path:
    """Resolve the ``.claude/ccy`` directory under ``project_root``."""
    return project_root.joinpath(*_CCY_DIR_PARTS)


def _active_wrapper_lines(ccy_env: Path) -> list[str]:
    """Non-comment lines of ``ccy.env`` that export the wrapper and name the supervisor."""
    if not ccy_env.is_file():
        return []
    try:
        content = ccy_env.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"an unreadable {ccy_env} yields no active wrapper lines ([]), so the supervisor is treated as not configured",
            level=logging.DEBUG,
        )
        return []
    lines: list[str] = []
    for raw in content.splitlines():
        stripped = raw.strip()
        if stripped.startswith(_COMMENT_PREFIX):
            continue
        if _WRAPPER_EXPORT_KEY in stripped and _SUPERVISOR_LAUNCHER_NAME in stripped:
            lines.append(stripped)
    return lines


def is_armed(ccy_env: Path) -> bool:
    """Armed = a non-comment line exports the wrapper referencing the supervisor."""
    return bool(_active_wrapper_lines(ccy_env))


def wrapper_execs_bare_script(ccy_env: Path) -> bool:
    """True when an active wrapper line still execs ``claude-supervise.py`` directly.

    Such an install bypasses the version-gating launcher, so an unsupported
    system Python crashes the supervisor and Claude Code cannot start. A daemon
    upgrade repoints the line at the launcher.
    """
    return any(_SUPERVISOR_SCRIPT_NAME in line for line in _active_wrapper_lines(ccy_env))


def wrapper_names_launcher(ccy_env: Path) -> bool:
    """True when an active wrapper line names the launcher (not just the bare script)."""
    pattern = re.compile(re.escape(_SUPERVISOR_LAUNCHER_NAME) + r"(?!\.py)")
    return any(pattern.search(line) for line in _active_wrapper_lines(ccy_env))


def supervisor_relevance(context: RelevanceContext) -> Relevance:
    """Relevance verdict shared by every handler that only serves the supervisor.

    Plan 00330: ``goal_injection``, ``compaction_signal``,
    ``model_fallback_detector`` and ``tool_disable_advisor`` are actuated by
    the ccy PTY supervisor, so the config-optimisation review recommends
    them only where one is ARMED (``ccy.env`` exports the wrapper). One
    predicate here rather than four copies that could disagree.
    """
    return Relevance.when(
        is_armed(ccy_dir(context.project_root) / _CCY_ENV_NAME),
        present="the ccy supervisor is armed in .claude/ccy/ccy.env",
        absent="no armed ccy supervisor (.claude/ccy/ccy.env does not export the wrapper)",
    )


def daemon_untracked_dir(project_root: Path) -> Path:
    """Resolve the daemon untracked dir (install-mode-aware) from the root.

    The mode rule is ``install_layout`` -- the one definition -- not a copy of
    it, and no ``ProjectContext`` is needed (callers may pass a fallback cwd).
    """
    return get_untracked_dir(project_root)


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
        log_and_continue(
            logger,
            exc,
            reason=f"a liveness probe that fails for pid {pid} treats it as not alive (False), so a corrupt pid never reads as a live supervisor",
            level=logging.DEBUG,
        )
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
        log_and_continue(
            logger,
            exc,
            reason=f"an unreadable or invalid status file {status_path} reads as an empty status ({{}}), so the supervisor is treated as not reporting",
            level=logging.DEBUG,
        )
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
        log_and_continue(
            logger,
            exc,
            reason=f"a supervisor source {script} that cannot be hashed cannot be shown to match the armed one, so it is reported as not live (False)",
            level=logging.DEBUG,
        )
        return False
    return running_hash == ondisk_hash
