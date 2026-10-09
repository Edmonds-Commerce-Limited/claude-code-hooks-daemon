"""Which threads of one Claude Code session hold the declared crons (Plan 00470 Task 6.4).

Claude Code can open extra agent threads inside one session. To the hooks each
is a separate session: its own ``session_id``, its own transcript, its own
(empty) ``session_crons``, and a ``SessionStart`` reporting ``source:
"startup"``. Nothing in a payload says "this is a later thread". Left alone,
``cron_stop_enforcer`` would demand the declared ``persistent_crons`` at every
thread's stop and each thread would run its own copy of every job.

**Process ancestry does tell them apart.** Once a second thread exists, every
thread runs as a worker under its own ``bg-pty-host``, all under one
``claude daemon run --origin transient --spawned-by {...}`` process (RESEARCH.md,
"Probe results (Task 6.3)"). That process is the grouping key. Within the
group:

- the INITIAL thread's worker carries ``--fork-session`` and ``--resume``;
- a thread opened later is a claimed pre-started spare, ``--bg-spare``.

The holder is chosen by that shape, never by which thread's hook arrived first:
the initial thread's single-thread phase has no ``claude daemon run`` above it,
so it produces no group, and the new thread's ``SessionStart`` is usually the
first event to see one.

**The holder is a live process.** The registry stores the holder's worker pid
plus start time. A claimant takes over when that process is gone or is a
different process on a reused pid. The holder is compared by worker, not by
``session_id``, so ``/clear`` (a new session id in the same worker) stays the
holder.

**Where the pid comes from.** The daemon answers hooks over a Unix socket, so the
connected hook process is knowable by ``SO_PEERCRED``; ``daemon/server.py``
stamps it on the payload as :attr:`HookInputField.PEER_PID`, replacing any value
the caller supplied.

**Fail-safe toward today's behaviour: when unsure, the session HOLDS.** These
are undocumented Claude Code internals, so every failure to learn the placement
(no stamped pid, an unreadable or foreign ``/proc``, a chain that never reaches
such an ancestor, a worker of an unrecognised shape, a scan that cannot finish,
an unwritable registry) means "no exemption". The walk is bounded in depth and
by a deadline, reads only ``/proc/<pid>/stat`` and ``/proc/<pid>/cmdline``, and
never signals a process.

A group is keyed by the ancestor's pid PLUS its start time, because pids are
reused. The group-to-holder map lives under the daemon's untracked directory, so
it survives a daemon restart.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.blockage_marker import write_json_atomically
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

#: Placed under ``ProjectContext.daemon_untracked_dir()``.
THREAD_GROUPS_FILENAME: Final[str] = "session-thread-groups.json"

PROC_ROOT: Final[Path] = Path("/proc")

#: Process-chain hops examined before giving up.
MAX_WALK_DEPTH: Final[int] = 32

#: Seconds the whole walk (or scan) may take before it gives up.
WALK_TIME_BUDGET_SECONDS: Final[float] = 0.25

#: Most ``/proc`` entries the initial-worker scan will look at; more is "unsure".
MAX_SCAN_ENTRIES: int = 4096

#: Groups remembered; the oldest are forgotten first.
MAX_TRACKED_GROUPS: Final[int] = 256

# Bytes read from a cmdline: the markers sit in the first few arguments.
_CMDLINE_READ_LIMIT: Final[int] = 8192

# Indexes in the fields following the ``)`` that closes ``comm`` in /proc/<pid>/stat.
_STAT_PPID_INDEX: Final[int] = 1
_STAT_STARTTIME_INDEX: Final[int] = 19

# ``claude daemon run --origin transient --spawned-by {"pid": N, ...}``.
_ARG_DAEMON: Final[str] = "daemon"
_ARG_RUN: Final[str] = "run"
_FLAG_ORIGIN: Final[str] = "--origin"
_ORIGIN_TRANSIENT: Final[str] = "transient"
_FLAG_SPAWNED_BY: Final[str] = "--spawned-by"
_DAEMON_WORD_MAX_INDEX: Final[int] = 2
_SPAWNED_BY_PID_PATTERN: Final[re.Pattern[str]] = re.compile(r'^\{\s*"pid"\s*:\s*\d+')

# A thread's worker. The initial thread's carries both flags; a later thread is a spare.
_FLAG_FORK_SESSION: Final[str] = "--fork-session"
_FLAG_RESUME: Final[str] = "--resume"
_FLAG_BG_SPARE: Final[str] = "--bg-spare"

_KEY_GROUPS: Final[str] = "groups"
_FIELD_SESSION: Final[str] = "holder_session"
_FIELD_WORKER_PID: Final[str] = "worker_pid"
_FIELD_WORKER_START: Final[str] = "worker_start"

_registry_lock = threading.Lock()
_warned_paths: set[str] = set()


def reset_warned_paths() -> None:
    """Forget which corrupt registries were already reported (tests)."""
    _warned_paths.clear()


@dataclass(frozen=True)
class ProcessId:
    """A process, identified by pid plus start time so a reused pid is another process."""

    pid: int
    start_time: int

    @property
    def key(self) -> str:
        """``pid:start_time``."""
        return f"{self.pid}:{self.start_time}"


class WorkerKind(StrEnum):
    """What the thread's worker process says about the thread."""

    INITIAL = "initial"
    SPARE = "spare"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ThreadPlacement:
    """Where a hook sits: its session's group, and which thread's worker it runs under."""

    group: ProcessId
    worker: ProcessId | None
    kind: WorkerKind


@dataclass(frozen=True)
class OtherHolder:
    """Another thread holds the crons; ``session_id`` is None when not yet known."""

    session_id: str | None


@dataclass(frozen=True)
class _ProcessInfo:
    ppid: int
    start_time: int
    argv: tuple[str, ...]

    @property
    def alive(self) -> bool:
        return self.start_time >= 0


_GONE: Final[_ProcessInfo] = _ProcessInfo(ppid=-1, start_time=-1, argv=())


def _parse_stat(text: str) -> tuple[int, int] | None:
    """``(ppid, start_time)`` from a stat line; comm may hold spaces and parentheses."""
    close = text.rfind(")")
    if close < 0:
        return None
    fields = text[close + 1 :].split()
    if len(fields) <= _STAT_STARTTIME_INDEX:
        return None
    ppid, start = fields[_STAT_PPID_INDEX], fields[_STAT_STARTTIME_INDEX]
    if not (ppid.isdecimal() and start.isdecimal()):
        return None
    return int(ppid), int(start)


def _read_process(proc_root: Path, pid: int) -> _ProcessInfo:
    """Stat and argv of ``pid``; ``_GONE`` when it exited or cannot be read."""
    proc = proc_root / str(pid)
    try:
        stat_text = (proc / "stat").read_text(encoding="utf-8", errors="replace")
        with open(proc / "cmdline", "rb") as handle:
            raw = handle.read(_CMDLINE_READ_LIMIT)
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason=(
                f"a process that exited or is unreadable mid-walk ({proc}) ends the "
                "thread-group walk, and a session whose placement is unknown holds the crons"
            ),
            level=logging.DEBUG,
        )
    else:
        parsed = _parse_stat(stat_text)
        if parsed is not None:
            argv = tuple(part.decode("utf-8", "replace") for part in raw.split(b"\0"))
            return _ProcessInfo(ppid=parsed[0], start_time=parsed[1], argv=argv)
    return _GONE


def _flag_value(argv: tuple[str, ...], flag: str) -> str | None:
    """The argument following ``flag``, or None when absent or last."""
    for index, arg in enumerate(argv[:-1]):
        if arg == flag:
            return argv[index + 1]
    return None


def _is_session_front_end_daemon(argv: tuple[str, ...]) -> bool:
    """Whether argv is ``claude daemon run --origin transient --spawned-by {"pid": N...}``."""
    for index in range(min(_DAEMON_WORD_MAX_INDEX + 1, len(argv) - 1)):
        if argv[index] == _ARG_DAEMON and argv[index + 1] == _ARG_RUN:
            rest = argv[index + 2 :]
            spawned_by = _flag_value(rest, _FLAG_SPAWNED_BY)
            return (
                _flag_value(rest, _FLAG_ORIGIN) == _ORIGIN_TRANSIENT
                and spawned_by is not None
                and _SPAWNED_BY_PID_PATTERN.match(spawned_by) is not None
            )
    return False


def _worker_kind(argv: tuple[str, ...]) -> WorkerKind:
    if _FLAG_FORK_SESSION in argv and _FLAG_RESUME in argv:
        return WorkerKind.INITIAL
    if _FLAG_BG_SPARE in argv:
        return WorkerKind.SPARE
    return WorkerKind.UNKNOWN


def find_thread_placement(
    pid: int,
    *,
    proc_root: Path = PROC_ROOT,
    max_depth: int = MAX_WALK_DEPTH,
    time_budget: float = WALK_TIME_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> ThreadPlacement | None:
    """Walk up from ``pid`` to its ``claude daemon run`` ancestor, noting its worker.

    Args:
        pid: The process to start from (the hook's caller).
        proc_root: The ``/proc`` mount; a directory of the same shape in tests.
        max_depth: Most processes examined.
        time_budget: Seconds before the walk gives up.
        clock: Monotonic clock, injectable for tests.

    Returns:
        The placement, or None when no such ancestor was reached for ANY reason
        (including an unreadable ``/proc``): the caller treats None as "not a
        threaded session".
    """
    started = clock()
    current = pid
    worker: ProcessId | None = None
    kind = WorkerKind.UNKNOWN
    for _ in range(max_depth):
        if current <= 1 or clock() - started > time_budget:
            return None
        info = _read_process(proc_root, current)
        if not info.alive:
            return None
        if _is_session_front_end_daemon(info.argv):
            return ThreadPlacement(
                group=ProcessId(current, info.start_time), worker=worker, kind=kind
            )
        if worker is None:
            found = _worker_kind(info.argv)
            if found is not WorkerKind.UNKNOWN:
                worker, kind = ProcessId(current, info.start_time), found
        current = info.ppid
    return None


class _ScanOutcome(StrEnum):
    FOUND = "found"
    ABSENT = "absent"
    UNSURE = "unsure"


@dataclass(frozen=True)
class _ScanResult:
    outcome: _ScanOutcome
    worker: ProcessId | None = None


def _scan_for_initial_worker(
    group: ProcessId,
    proc_root: Path,
    *,
    time_budget: float = WALK_TIME_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> _ScanResult:
    """Find a live initial-shape worker under ``group``; UNSURE if the scan cannot finish."""
    started = clock()
    try:
        names = [entry.name for entry in proc_root.iterdir()]
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason=(
                "an unlistable /proc means the initial worker cannot be looked for, and a "
                "session whose holder is unknown holds the crons"
            ),
            level=logging.DEBUG,
        )
        return _ScanResult(_ScanOutcome.UNSURE)
    candidates = [int(name) for name in names if name.isdecimal()]
    if len(candidates) > MAX_SCAN_ENTRIES:
        return _ScanResult(_ScanOutcome.UNSURE)
    for pid in candidates:
        if clock() - started > time_budget:
            return _ScanResult(_ScanOutcome.UNSURE)
        info = _read_process(proc_root, pid)
        if info.alive and _worker_kind(info.argv) is WorkerKind.INITIAL:
            placement = find_thread_placement(pid, proc_root=proc_root)
            if placement is not None and placement.group == group:
                return _ScanResult(_ScanOutcome.FOUND, ProcessId(pid, info.start_time))
    return _ScanResult(_ScanOutcome.ABSENT)


@dataclass(frozen=True)
class _Holder:
    session_id: str
    worker: ProcessId


class ThreadGroupRegistry:
    """Persistent group-to-holder map: each group's holder is a live worker process."""

    def __init__(self, path: Path, max_groups: int = MAX_TRACKED_GROUPS) -> None:
        """Bind to the registry file ``path``, remembering at most ``max_groups``."""
        self._path = path
        self._max_groups = max_groups

    def _load(self) -> dict[str, _Holder]:
        """Group key to holder; empty when missing or untrustworthy."""
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            first = str(self._path) not in _warned_paths
            _warned_paths.add(str(self._path))
            log_and_continue(
                logger,
                exc,
                reason=(
                    f"an unreadable thread-group registry {self._path} is treated as empty, "
                    "so the caller holds the crons as before; it is rewritten on the next claim"
                ),
                level=logging.WARNING if first else logging.DEBUG,
            )
            return {}
        return self._parse(data)

    @staticmethod
    def _parse(data: Any) -> dict[str, _Holder]:
        groups = data.get(_KEY_GROUPS) if isinstance(data, dict) else None
        holders: dict[str, _Holder] = {}
        if not isinstance(groups, dict):
            return holders
        for key, entry in groups.items():
            if not (isinstance(key, str) and isinstance(entry, dict)):
                continue
            session = entry.get(_FIELD_SESSION)
            pid = entry.get(_FIELD_WORKER_PID)
            start = entry.get(_FIELD_WORKER_START)
            if isinstance(session, str) and isinstance(pid, int) and isinstance(start, int):
                holders[key] = _Holder(session, ProcessId(pid, start))
        return holders

    def _save(self, holders: dict[str, _Holder]) -> None:
        kept = list(holders.items())[-self._max_groups :]
        payload = {
            _KEY_GROUPS: {
                key: {
                    _FIELD_SESSION: holder.session_id,
                    _FIELD_WORKER_PID: holder.worker.pid,
                    _FIELD_WORKER_START: holder.worker.start_time,
                }
                for key, holder in kept
            }
        }
        try:
            write_json_atomically(self._path, payload)
        except OSError as exc:
            log_and_continue(
                logger,
                exc,
                reason=(
                    f"an unwritable thread-group registry {self._path} records no holder, so "
                    "every session keeps holding the crons as before"
                ),
            )

    def resolve(
        self, placement: ThreadPlacement, session_id: str, *, proc_root: Path = PROC_ROOT
    ) -> OtherHolder | None:
        """Whether ``session_id`` is a later thread whose crons another thread holds.

        Returns:
            None when this session holds the crons (it runs in the group's live
            holder worker, no live holder is recorded and it is the initial thread
            or no initial thread is alive, or anything is unsure); otherwise the
            other holder.

        Raises:
            ValueError: If ``session_id`` is empty.
        """
        if not session_id:
            raise ValueError("session_id must be non-empty")
        worker = placement.worker
        if worker is None:
            return None
        with _registry_lock:
            holders = self._load()
            recorded = holders.get(placement.group.key)
            if recorded is not None and _is_live(proc_root, recorded.worker):
                if recorded.worker != worker:
                    return OtherHolder(recorded.session_id or None)
                if recorded.session_id != session_id:
                    holders[placement.group.key] = _Holder(session_id, worker)
                    self._save(holders)
                return None
            if placement.kind is WorkerKind.INITIAL:
                holders[placement.group.key] = _Holder(session_id, worker)
                self._save(holders)
                return None
            scan = _scan_for_initial_worker(placement.group, proc_root)
            if scan.outcome is _ScanOutcome.UNSURE:
                return None
            if scan.outcome is _ScanOutcome.FOUND and scan.worker is not None:
                holders[placement.group.key] = _Holder("", scan.worker)
                self._save(holders)
                return OtherHolder(None)
            logger.info(
                "thread group %s has no live initial thread; session %s takes over",
                placement.group.key,
                session_id,
            )
            holders[placement.group.key] = _Holder(session_id, worker)
            self._save(holders)
            return None


def _is_live(proc_root: Path, process: ProcessId) -> bool:
    info = _read_process(proc_root, process.pid)
    return info.alive and info.start_time == process.start_time


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
) -> OtherHolder | None:
    """The other holder when this is NOT the session's initial thread, else None.

    Args:
        hook_input: The hook payload.
        initial_thread_only: ``persistent_crons.initial_thread_only``; False
            means every session holds the crons and nothing is read.
        registry_path: Where the group map persists; None means no persistence,
            so no exemption.
        proc_root: The ``/proc`` mount.

    Returns:
        :class:`OtherHolder` when this payload's session is a later thread of a
        Claude Code session whose initial thread is alive; None when it holds
        the crons, or when the placement cannot be established (no stamped pid,
        no session id, no ``claude daemon run`` ancestor, unreadable ``/proc``,
        an unrecognised worker, ...), all of which mean it holds as before.
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
    placement = find_thread_placement(pid, proc_root=proc_root)
    if placement is None:
        return None
    return ThreadGroupRegistry(registry_path).resolve(placement, session_id, proc_root=proc_root)
