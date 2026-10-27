"""Session ids found in the environment of a process and its descendants.

A Claude Code process exports ``CLAUDE_CODE_SESSION_ID`` to itself and to every
process it starts. A session therefore belongs to a supervisor only when that
id is in the environ of a process in the supervisor's own descendant tree. The
ccy supervisor applies the same rule on its side; this module is the daemon's
read-only copy of it, so the status line can ask the same question.

Every failure mode (no ``/proc``, a process that vanished, an unreadable
environ, a malformed ``stat``) contributes no ids. The callers' question is
"does this tree own that session", and "cannot tell" must read as "no".
"""

import logging
from pathlib import Path

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

SESSION_ENV_VAR = "CLAUDE_CODE_SESSION_ID"
_SESSION_ENV_PREFIX = f"{SESSION_ENV_VAR}=".encode()

# Index of the ppid within the fields that follow the closing parenthesis of
# the comm field in ``/proc/<pid>/stat`` (state, then ppid).
_STAT_PPID_FIELD_INDEX = 1


def session_ids_from_environ(environ: bytes) -> set[str]:
    """Extract ``CLAUDE_CODE_SESSION_ID`` value(s) from a NUL-delimited environ."""
    found: set[str] = set()
    for entry in environ.split(b"\x00"):
        if entry.startswith(_SESSION_ENV_PREFIX):
            value = entry[len(_SESSION_ENV_PREFIX) :].decode("utf-8", "replace").strip()
            if value:
                found.add(value)
    return found


def _stat_ppid(stat_line: str) -> int | None:
    """Parse the ppid from a ``/proc/<pid>/stat`` line, or None if malformed.

    The comm field is chosen by the process and may hold spaces and
    parentheses, so the fields are taken after the LAST ``)``.
    """
    close = stat_line.rfind(")")
    if close < 0:
        return None
    fields = stat_line[close + 1 :].split()
    if len(fields) <= _STAT_PPID_FIELD_INDEX or not fields[_STAT_PPID_FIELD_INDEX].isdigit():
        return None
    return int(fields[_STAT_PPID_FIELD_INDEX])


def _children_by_parent(proc_root: Path) -> dict[int, list[int]]:
    """Map each parent pid to its child pids, from every readable ``stat``."""
    children: dict[int, list[int]] = {}
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat_line = (entry / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            log_and_continue(
                logger,
                e,
                reason="a process that vanished or hides its stat is in no tree (skipped)",
                level=logging.DEBUG,
            )
            continue
        ppid = _stat_ppid(stat_line)
        if ppid is not None:
            children.setdefault(ppid, []).append(int(entry.name))
    return children


def _read_environ(proc_root: Path, pid: int) -> bytes:
    """Read ``/proc/<pid>/environ``; empty bytes when it cannot be read."""
    try:
        return (proc_root / str(pid) / "environ").read_bytes()
    except OSError as e:
        log_and_continue(
            logger,
            e,
            reason="an unreadable environ (exited, EPERM) contributes no session id",
            level=logging.DEBUG,
        )
        return b""


def descendant_session_ids(root_pid: int, proc_root: Path) -> frozenset[str]:
    """Collect session ids from ``root_pid`` and every descendant of it.

    The cost is one ``stat`` read per numeric entry under ``proc_root`` plus one
    ``environ`` read per member of the subtree; it is bounded by the process
    table. Empty when ``proc_root`` cannot be listed or ``root_pid`` is gone.
    """
    try:
        children = _children_by_parent(proc_root)
    except OSError as e:
        log_and_continue(
            logger,
            e,
            reason="a process table that cannot be listed owns no session (empty set)",
            level=logging.DEBUG,
        )
        return frozenset()
    if not (proc_root / str(root_pid)).is_dir():
        return frozenset()

    found: set[str] = set()
    visited: set[int] = set()
    pending = [root_pid]
    while pending:
        pid = pending.pop()
        if pid in visited:
            continue
        visited.add(pid)
        found |= session_ids_from_environ(_read_environ(proc_root, pid))
        pending.extend(children.get(pid, ()))
    return frozenset(found)
