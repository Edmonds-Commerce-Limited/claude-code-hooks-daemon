"""Which threads of one Claude Code session hold the declared crons (Plan 00470 Task 6.4).

Claude Code can open extra agent threads inside one session. To the hooks each
is a separate session: its own ``session_id``, its own transcript, its own
(empty) ``session_crons``, and a ``SessionStart`` reporting ``source:
"startup"``. Nothing in a payload says "this is a later thread". Left alone,
``cron_stop_enforcer`` would demand the declared ``persistent_crons`` at every
thread's stop and each thread would run its own copy of every job.

**Process ancestry does tell them apart.** Every thread of a session runs under
one ``claude daemon run ... --spawned-by {...}`` process (RESEARCH.md, "Probe
results (Task 6.3)"). That process is the grouping key: the first ``session_id``
seen under it is the initial thread and holds the crons; later ones are exempt.

**Where the pid comes from.** The daemon answers hooks over a Unix socket, so the
connected hook process is knowable by ``SO_PEERCRED``; ``daemon/server.py``
stamps it on the payload as :attr:`HookInputField.PEER_PID`. A hook is a
descendant of its thread's worker, so walking the ppid chain from there reaches
the ``claude daemon run`` ancestor.

**Fail-safe toward today's behaviour.** These are undocumented Claude Code
internals, so every failure to learn the group (no stamped pid, an unreadable or
foreign ``/proc``, a chain that never reaches such an ancestor, an unwritable
registry) means "no exemption": the session holds the crons, exactly as before.
The walk is bounded in depth and by a deadline, reads only ``/proc/<pid>/stat``
and ``/proc/<pid>/cmdline``, and never signals a process.

A group is keyed by the ancestor's pid PLUS its start time, because pids are
reused. The group-to-holder map lives under the daemon's untracked directory, so
it survives a daemon restart.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.blockage_marker import write_json_atomically

logger = logging.getLogger(__name__)

#: Placed under ``ProjectContext.daemon_untracked_dir()``.
THREAD_GROUPS_FILENAME: Final[str] = "session-thread-groups.json"

PROC_ROOT: Final[Path] = Path("/proc")

#: Process-chain hops examined before giving up.
MAX_WALK_DEPTH: Final[int] = 32

#: Seconds the whole walk may take before it gives up.
WALK_TIME_BUDGET_SECONDS: Final[float] = 0.25

#: Groups remembered; the oldest are forgotten first.
MAX_TRACKED_GROUPS: Final[int] = 256

# Bytes read from a cmdline: the markers sit in the first few arguments.
_CMDLINE_READ_LIMIT: Final[int] = 8192

# Index of ``starttime`` (stat field 22) in the fields following the ``)`` of comm.
_STAT_FIELDS_AFTER_COMM_STARTTIME: Final[int] = 19
_STAT_FIELDS_AFTER_COMM_PPID: Final[int] = 1

# ``claude daemon run --spawned-by ...``: how far in argv the ``daemon`` word may sit.
_DAEMON_WORD_MAX_INDEX: Final[int] = 2
_SPAWNED_BY_FLAG: Final[str] = "--spawned-by"

_KEY_GROUPS: Final[str] = "groups"
_FIELD_HOLDER: Final[str] = "holder"

_registry_lock = threading.Lock()


@dataclass(frozen=True)
class ThreadGroup:
    """The ``claude daemon run`` process all threads of one session share."""

    pid: int
    start_time: int

    @property
    def key(self) -> str:
        """The registry key: pid plus start time, so a reused pid is a new group."""
        return f"{self.pid}:{self.start_time}"


def _read_stat(proc_root: Path, pid: int) -> tuple[int, int] | None:
    """``(ppid, start_time)`` of ``pid``, or None when unreadable or malformed."""
    try:
        text = (proc_root / str(pid) / "stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # comm is parenthesised and may itself contain spaces and parentheses.
    close = text.rfind(")")
    if close < 0:
        return None
    fields = text[close + 1 :].split()
    if len(fields) <= _STAT_FIELDS_AFTER_COMM_STARTTIME:
        return None
    try:
        return (
            int(fields[_STAT_FIELDS_AFTER_COMM_PPID]),
            int(fields[_STAT_FIELDS_AFTER_COMM_STARTTIME]),
        )
    except ValueError:
        return None


def _is_daemon_run(proc_root: Path, pid: int) -> bool:
    """Whether ``pid`` is a ``claude daemon run --spawned-by ...`` process."""
    try:
        with open(proc_root / str(pid) / "cmdline", "rb") as handle:
            raw = handle.read(_CMDLINE_READ_LIMIT)
    except OSError:
        return False
    argv = [part.decode("utf-8", "replace") for part in raw.split(b"\0")]
    for index in range(min(_DAEMON_WORD_MAX_INDEX + 1, len(argv) - 1)):
        if argv[index] == "daemon" and argv[index + 1] == "run":
            return _SPAWNED_BY_FLAG in argv[index + 2 :]
    return False


def find_thread_group(
    pid: int,
    *,
    proc_root: Path = PROC_ROOT,
    max_depth: int = MAX_WALK_DEPTH,
    time_budget: float = WALK_TIME_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> ThreadGroup | None:
    """The nearest ``claude daemon run --spawned-by`` ancestor of ``pid``, if any.

    Args:
        pid: The process to start from (the hook's caller).
        proc_root: The ``/proc`` mount; a directory of the same shape in tests.
        max_depth: Most processes examined.
        time_budget: Seconds before the walk gives up.
        clock: Monotonic clock, injectable for tests.

    Returns:
        The group, or None when nothing was found for ANY reason (including an
        unreadable ``/proc``): the caller treats None as "not a threaded session".
    """
    started = clock()
    current = pid
    for _ in range(max_depth):
        if current <= 1 or clock() - started > time_budget:
            return None
        stat = _read_stat(proc_root, current)
        if stat is None:
            return None
        ppid, start_time = stat
        if _is_daemon_run(proc_root, current):
            return ThreadGroup(pid=current, start_time=start_time)
        current = ppid
    return None


class ThreadGroupRegistry:
    """Persistent group-to-holder map: the first session seen per group holds."""

    def __init__(self, path: Path, max_groups: int = MAX_TRACKED_GROUPS) -> None:
        """Bind to the registry file ``path``, remembering at most ``max_groups``."""
        self._path = path
        self._max_groups = max_groups

    def _load(self) -> dict[str, str]:
        """Group key to holder session id; empty when missing or untrustworthy."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logger.warning("thread-group registry %s unreadable: %s", self._path, exc)
            return {}
        groups = data.get(_KEY_GROUPS) if isinstance(data, dict) else None
        if not isinstance(groups, dict):
            return {}
        holders: dict[str, str] = {}
        for key, entry in groups.items():
            holder = entry.get(_FIELD_HOLDER) if isinstance(entry, dict) else None
            if isinstance(key, str) and isinstance(holder, str) and holder:
                holders[key] = holder
        return holders

    def claim(self, group: ThreadGroup, session_id: str) -> str:
        """Record ``session_id`` as the group's holder unless one is recorded.

        Returns:
            The group's holder: ``session_id`` itself when it is the first seen
            (or when the registry cannot be written, which keeps today's
            behaviour of every session holding the crons).

        Raises:
            ValueError: If ``session_id`` is empty.
        """
        if not session_id:
            raise ValueError("session_id must be non-empty")
        with _registry_lock:
            holders = self._load()
            existing = holders.get(group.key)
            if existing is not None:
                return existing
            holders[group.key] = session_id
            kept = list(holders.items())[-self._max_groups :]
            payload = {_KEY_GROUPS: {key: {_FIELD_HOLDER: holder} for key, holder in kept}}
            try:
                write_json_atomically(self._path, payload)
            except OSError as exc:
                logger.warning("thread-group registry %s not written: %s", self._path, exc)
            return session_id


def default_registry_path() -> Path | None:
    """The project's registry file, or None when there is no project context."""
    if not ProjectContext.is_initialized():
        return None
    return ProjectContext.daemon_untracked_dir() / THREAD_GROUPS_FILENAME


def peer_pid_of(hook_input: Mapping[str, Any]) -> int | None:
    """The hook process pid the daemon stamped on the payload, if usable."""
    pid = hook_input.get(HookInputField.PEER_PID)
    if isinstance(pid, int) and not isinstance(pid, bool) and pid > 1:
        return pid
    return None


def initial_thread_holder_elsewhere(
    hook_input: Mapping[str, Any],
    *,
    initial_thread_only: bool,
    registry_path: Path | None,
    proc_root: Path = PROC_ROOT,
) -> str | None:
    """The session id holding the crons when this is NOT the session's initial thread.

    Args:
        hook_input: The hook payload.
        initial_thread_only: ``persistent_crons.initial_thread_only``; False
            means every session holds the crons and nothing is read.
        registry_path: Where the group map persists; None means no persistence,
            so no exemption.
        proc_root: The ``/proc`` mount.

    Returns:
        The initial thread's ``session_id`` when this payload's session is a
        later thread of the same Claude Code session; None when it is the
        initial thread, or when the grouping cannot be established (no stamped
        pid, no session id, no ``claude daemon run`` ancestor, unreadable
        ``/proc``), all of which mean the session holds the crons as before.
    """
    session_id = hook_input.get(HookInputField.SESSION_ID)
    pid = peer_pid_of(hook_input)
    if (
        not initial_thread_only
        or registry_path is None
        or pid is None
        or not isinstance(session_id, str)
        or not session_id
    ):
        return None
    group = find_thread_group(pid, proc_root=proc_root)
    if group is None:
        return None
    holder = ThreadGroupRegistry(registry_path).claim(group, session_id)
    return None if holder == session_id else holder
