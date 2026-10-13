"""Which sub-agents may run the full QA gate, and whether it is free (Plan 00518).

Two questions the full-QA blocker asks once a full run is seen:

1. :func:`exempting_entry` -- is the calling agent's DEFINITION type listed in
   ``exempt_agent_types``? The payload's ``agent_type`` is the dispatch name for
   a named agent, so it is resolved through the dispatch record first
   (:mod:`agent_dispatch_registry`). Anything that cannot be placed -- no
   ``agent_type``, an empty one, no session to look a name up in -- is not
   exempt: a guard that cannot tell who is asking must keep denying.
2. :func:`probe_full_qa_lock` -- the exemption comes with one run at a time,
   which is the host-wide full-QA lock the pytest sink already enforces. The
   probe takes the lock without waiting and lets go at once; flock is released
   by the kernel when a holder dies, so a dead holder can never block.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

from claude_code_hooks_daemon.qa.full_qa_lock import acquire_full_qa_lock, host_lock_path
from claude_code_hooks_daemon.utils.agent_dispatch_registry import effective_agent_type


def declared_exempt_types(raw: object) -> list[str]:
    """The usable entries of the ``exempt_agent_types`` option.

    Exact, non-empty strings. A non-list value declares nothing (the caller
    reports it through :func:`exempt_types_problem`).
    """
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, str) and entry.strip()]


def exempt_types_problem(raw: object) -> str | None:
    """Why the option cannot be used as written, or None when it is fine."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        return f"must be a list of agent type names, got {type(raw).__name__}"
    bad = [entry for entry in raw if not (isinstance(entry, str) and entry.strip())]
    if bad:
        return f"entries must be non-empty strings, ignoring {bad!r}"
    return None


def exempting_entry(
    declared: list[str], untracked_dir: Path, session_id: object, agent_type: object
) -> str | None:
    """The ``declared`` entry that exempts this caller, or None.

    Matching is exact: no stripping, no case folding, no globs.
    """
    if not declared:
        return None
    if not isinstance(agent_type, str) or not agent_type.strip():
        return None
    if not isinstance(session_id, str) or not session_id:
        return None
    resolved = effective_agent_type(untracked_dir, session_id, agent_type)
    return resolved if resolved in declared else None


class LockState(Enum):
    """What a non-blocking probe of the host-wide full-QA lock found."""

    FREE = "free"
    HELD = "held"
    UNKNOWN = "unknown"  # git could not locate the lock, so nothing can be said


def probe_full_qa_lock(cwd: Path) -> LockState:
    """Take the host-wide full-QA lock without waiting, and let go at once."""
    try:
        with acquire_full_qa_lock(cwd, blocking=False):
            return LockState.FREE
    except BlockingIOError:
        return LockState.HELD
    except OSError:
        return LockState.UNKNOWN


def lock_path_text(cwd: Path) -> str:
    """The lock file's path for a message, or a placeholder when git cannot say."""
    try:
        return str(host_lock_path(cwd))
    except OSError:
        return "(lock location unknown)"


def lock_holder_text(cwd: Path) -> str:
    """Who holds the lock, as far as the holder's stamp says and its pid is alive.

    ``llm_qa.py`` stamps ``pid=``, ``checkout=`` and ``started=`` lines into the
    lock file while it holds it. Diagnostic only: the decision is flock's. A
    holder that stamps nothing (a bare whole-suite run), a dead pid or an
    unreadable file is reported as unnamed.
    """
    unnamed = "the holder is not named"
    try:
        content = host_lock_path(cwd).read_text(encoding="utf-8")
    except OSError:
        return unnamed
    fields = dict(line.split("=", 1) for line in content.splitlines() if "=" in line)
    pid_text = fields.get("pid", "")
    if not pid_text.isdigit() or not _pid_is_alive(int(pid_text)):
        return unnamed
    checkout = fields.get("checkout", "unknown checkout")
    started = fields.get("started", "unknown time")
    return f"held by pid {pid_text} in {checkout}, started {started}"


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive, owned by someone else
    return True
