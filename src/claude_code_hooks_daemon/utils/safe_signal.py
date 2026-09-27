"""The one place a nonzero signal is sent to another process (Plan 00466 N59).

A signal is only as safe as the proof that its pid names the intended process.
Twice a unit test killed the whole container: a ``MagicMock`` Popen's pid
coerces to 1, and ``os.killpg(os.getpgid(1), SIGKILL)`` took out init. A PID
file is no better a proof, because PID files survive a container restart and a
restarted container reuses small pids, so a stale file can name Claude Code.

Every nonzero signal this project sends therefore goes through one of two
proofs, and ``scripts/qa/check_signal_targets.py`` fails QA on one that does
not:

* :func:`signal_verified_daemon` / :func:`stop_verified_daemon` /
  :func:`verified_daemon_process` — the pid's command line is a daemon SERVER
  for THIS project root, not merely any daemon. Where the kernel makes
  pidfds, one is opened BEFORE the proof and carries every signal, so a pid
  reused at any point after it was pinned cannot receive one (Plan 00466
  N206); elsewhere the proven ``psutil`` handle does, which re-checks the
  pid's start time before it sends.
* :func:`signal_own_session_child` — a group kill, only to a child this code
  spawned with ``start_new_session=True`` that is still running and still
  leads its own group.

Both refuse a pid that is not a plain ``int`` above 1 (a ``bool`` and a
``MagicMock`` both coerce to 1), this process, any ancestor, and this
process's own group. A refusal raises :class:`RefusedSignalTarget`; security
callers fail closed, so a pid whose identity cannot be read is refused too.
"""

from __future__ import annotations

import contextlib
import errno
import os
import select
import signal
from collections.abc import Iterator
from enum import Enum
from pathlib import Path
from typing import Final, Protocol

import psutil

from claude_code_hooks_daemon.daemon.process_verification import (
    _attributed_root,
    _is_daemon_server_process,
    root_names_project,
)

#: Init's pid and the group it leads; never a target.
_INIT_PID = 1

#: ``pidfd_open`` failures that mean this kernel or container makes no pidfds
#: (not built in, refused by seccomp, no anonymous inode filesystem) or has no
#: descriptor to spare, rather than anything about the pid. psutil's own wait
#: falls back on the last three too.
_NO_PIDFD_ERRNOS: Final = frozenset(
    {errno.ENOSYS, errno.EPERM, errno.ENODEV, errno.EMFILE, errno.ENFILE}
)

_MS_PER_SECOND: Final = 1000

#: How far a process's start time may read as later than it was. psutil
#: adds its ticks since boot to the boot time, which the kernel gives in
#: whole seconds.
_START_TIME_PRECISION_SECONDS: Final = 1.0


class RefusedSignalTarget(Exception):
    """The pid is not provably the intended process, so no signal was sent."""


class SpawnedChild(Protocol):
    """What :func:`signal_own_session_child` reads of a ``subprocess.Popen``."""

    @property
    def pid(self) -> int: ...

    def poll(self) -> int | None: ...


def _plain_pid(pid: object) -> int:
    """``pid`` itself when it is a real ``int`` above 1; refuse anything else.

    ``type(...) is int`` rather than ``isinstance``: ``True`` is an ``int``,
    and a ``MagicMock`` is not one but coerces to 1 wherever an index is taken.
    """
    if type(pid) is not int:
        raise RefusedSignalTarget(f"pid {pid!r} is a {type(pid).__name__}, not an int")
    if pid <= _INIT_PID:
        raise RefusedSignalTarget(f"pid {pid} is init, our own group or every process")
    return pid


def _refuse_own_lineage(pid: int) -> None:
    """Refuse this process, the leader of its group, and every ancestor up to init."""
    if pid == os.getpid():
        raise RefusedSignalTarget(f"pid {pid} is this process")
    if pid == os.getpgid(0):
        raise RefusedSignalTarget(f"pid {pid} leads this process's own group")
    ancestors = {parent.pid for parent in psutil.Process().parents()}
    if pid in ancestors:
        raise RefusedSignalTarget(f"pid {pid} is an ancestor of this process")


def _refuse_started_after(process: psutil.Process, recorded_at: float) -> None:
    """Refuse ``process`` when it started after the record naming it was written.

    A daemon writes its PID file, and names itself in the launch lock, after
    it has started, and a launcher takes that lock after it has; so a
    process that started later holds a pid reused since (review 10, R10-3).
    """
    try:
        started = process.create_time()
    except psutil.NoSuchProcess as gone:
        raise ProcessLookupError(f"no process has pid {process.pid}") from gone
    except psutil.AccessDenied as denied:
        raise RefusedSignalTarget(f"cannot read the start time of pid {process.pid}") from denied
    if started > recorded_at + _START_TIME_PRECISION_SECONDS:
        raise RefusedSignalTarget(
            f"pid {process.pid} started after the record naming it was written, "
            "so it holds a pid reused since"
        )


def verified_daemon_process(
    pid: object,
    *,
    project_root: Path | str,
    logical_root: str | None = None,
    recorded_at: float | None = None,
) -> psutil.Process:
    """A handle on ``pid``, proven to be the daemon server for ``project_root``.

    ``logical_root`` is the caller's unresolved spelling of that root (see
    :func:`root_names_project`). ``recorded_at`` is when the record the pid
    was read from (a PID file, the launch lock) was last written, if it was
    read from one: a process that started after it is refused.

    The returned :class:`psutil.Process` remembers the process's start time and
    re-checks it before every ``send_signal``/``terminate``/``kill``. That
    narrows the reuse window but does not close it: a pid reused between the
    re-check and the ``kill`` is signalled (Plan 00466 N206). Only
    :func:`signal_verified_daemon` and :func:`stop_verified_daemon` close it,
    through a pidfd pinned before this proof, and only where the kernel makes
    pidfds; elsewhere they fall back on this handle and its window. A caller
    that signals through the handle itself has the window.

    A command line is anyone's to write, so it proves nothing about a process
    another user owns (Plan 00466 round 6, P5-1): both its real and effective
    uids must be this process's effective uid. Root may signal every process,
    so permission to signal is no proof of ownership.

    Raises:
        RefusedSignalTarget: ``pid`` is not a plain int above 1, is this
            process or an ancestor, belongs to another user, started after
            ``recorded_at``, is not a daemon server, serves another project
            root, or cannot be inspected.
        ProcessLookupError: No process has this pid.
    """
    checked = _plain_pid(pid)
    _refuse_own_lineage(checked)
    try:
        process = psutil.Process(checked)
    except psutil.NoSuchProcess as gone:
        raise ProcessLookupError(f"no process has pid {checked}") from gone
    try:
        uids = process.uids()
    except psutil.NoSuchProcess as gone:
        raise ProcessLookupError(f"no process has pid {checked}") from gone
    except psutil.AccessDenied as denied:
        raise RefusedSignalTarget(f"cannot read the owner of pid {checked}") from denied
    euid = os.geteuid()
    if uids.real != euid or uids.effective != euid:
        raise RefusedSignalTarget(
            f"pid {checked} belongs to another user (uid {uids.real}), not {euid}"
        )
    if recorded_at is not None:
        _refuse_started_after(process, recorded_at)
    try:
        cmdline = process.cmdline()
    except psutil.NoSuchProcess as gone:
        raise ProcessLookupError(f"no process has pid {checked}") from gone
    except psutil.AccessDenied as denied:
        raise RefusedSignalTarget(f"cannot read the command line of pid {checked}") from denied

    if not _is_daemon_server_process(cmdline):
        raise RefusedSignalTarget(f"pid {checked} is not a daemon server: {cmdline!r}")
    attributed = _attributed_root(process, cmdline)
    if attributed.root is None:
        raise RefusedSignalTarget(f"pid {checked} is a daemon server, but {attributed.refusal}")
    if not root_names_project(attributed.root, project_root, logical_root=logical_root):
        raise RefusedSignalTarget(
            f"pid {checked} is a daemon for project root {attributed.root!r}, "
            f"not {str(project_root)!r}"
        )
    return process


@contextlib.contextmanager
def _pinned(pid: object) -> Iterator[int | None]:
    """A pidfd naming ``pid``'s process, opened before anything proves it.

    The proof then reads whatever process holds the pid, and every signal
    goes through this fd. A pid reused after the pin only makes the send
    fail, where psutil's start-time re-check left a gap before its ``kill``
    (Plan 00466 N206). None where this kernel makes no pidfds.

    Raises:
        RefusedSignalTarget: See :func:`_plain_pid` and :func:`_refuse_own_lineage`;
            or ``pidfd_open`` failed for a reason other than this kernel
            making no pidfds, so the pid cannot be pinned (review 8, R8-4).
        ProcessLookupError: No process has this pid.
    """
    checked = _plain_pid(pid)
    _refuse_own_lineage(checked)
    pidfd: int | None = None
    if hasattr(os, "pidfd_open"):
        try:
            pidfd = os.pidfd_open(checked)
        except ProcessLookupError:
            raise
        except OSError as unavailable:
            if unavailable.errno not in _NO_PIDFD_ERRNOS:
                raise RefusedSignalTarget(
                    f"pid {checked} cannot be pinned: {unavailable.strerror}"
                ) from unavailable
    try:
        yield pidfd
    finally:
        if pidfd is not None:
            os.close(pidfd)


def _send(process: psutil.Process, pidfd: int | None, sig: int) -> None:
    """Deliver ``sig`` through the pin, or the proven handle where there is none.

    Raises:
        ProcessLookupError: The process is gone, or its pid was reused.
        PermissionError: This process may not signal it.
    """
    if pidfd is not None:
        signal.pidfd_send_signal(pidfd, sig)
        return
    try:
        process.send_signal(sig)
    except psutil.NoSuchProcess as gone:
        raise ProcessLookupError(f"daemon pid {process.pid} has exited") from gone
    except psutil.AccessDenied as denied:
        raise PermissionError(f"not permitted to signal daemon pid {process.pid}") from denied


def _exited_within(process: psutil.Process, pidfd: int | None, seconds: float) -> bool:
    """True once the pinned process exits inside ``seconds``.

    A pidfd polls readable when its own process exits, so a pid reused
    meanwhile cannot hold the wait open.
    """
    if pidfd is not None:
        poller = select.poll()
        poller.register(pidfd, select.POLLIN)
        return bool(poller.poll(int(seconds * _MS_PER_SECOND)))
    try:
        process.wait(timeout=seconds)
    except psutil.TimeoutExpired:
        return False
    return True


def signal_verified_daemon(pid: object, sig: int, *, project_root: Path | str) -> None:
    """Send ``sig`` to ``pid`` only once it is proven to be this project's daemon.

    Raises:
        RefusedSignalTarget: See :func:`verified_daemon_process`.
        ProcessLookupError: The process is gone, or its pid was reused.
        PermissionError: This process may not signal it.
    """
    with _pinned(pid) as pidfd:
        process = verified_daemon_process(pid, project_root=project_root)
        _send(process, pidfd, sig)


class DaemonStop(Enum):
    """How :func:`stop_verified_daemon` left the daemon."""

    TERMINATED = "terminated"
    KILLED = "killed"
    ALREADY_GONE = "already_gone"
    SURVIVED = "survived"


def stop_verified_daemon(
    pid: object,
    *,
    project_root: Path | str,
    grace_seconds: float,
    kill_grace_seconds: float | None = None,
    logical_root: str | None = None,
    recorded_at: float | None = None,
) -> DaemonStop:
    """SIGTERM this project's daemon at ``pid``, then SIGKILL it after the grace.

    The identity is proven once, and the pin taken before it (or, without
    pidfds, the handle's start-time check) stops a pid reused during the
    grace from receiving the SIGKILL.

    Args:
        pid: Candidate daemon pid.
        project_root: The project this daemon must serve.
        grace_seconds: How long to wait for SIGTERM before escalating.
        kill_grace_seconds: How long to wait for the OS to reap the process
            after SIGKILL, which a process cannot catch, block or ignore, so
            this budget only needs to cover reaping -- not another chance to
            exit gracefully. Defaults to ``grace_seconds`` when omitted.
        logical_root: The caller's unresolved spelling of ``project_root``,
            see :func:`verified_daemon_process`.
        recorded_at: When the record ``pid`` was read from was last written,
            see :func:`verified_daemon_process`. A caller that read the pid
            from a PID file or the launch lock passes it.

    Raises:
        RefusedSignalTarget: See :func:`verified_daemon_process`.
        PermissionError: This process may not signal it.
    """
    kill_wait = grace_seconds if kill_grace_seconds is None else kill_grace_seconds
    try:
        with _pinned(pid) as pidfd:
            process = verified_daemon_process(
                pid,
                project_root=project_root,
                logical_root=logical_root,
                recorded_at=recorded_at,
            )
            _send(process, pidfd, signal.SIGTERM)
            if _exited_within(process, pidfd, grace_seconds):
                return DaemonStop.TERMINATED
            _send(process, pidfd, signal.SIGKILL)
            if _exited_within(process, pidfd, kill_wait):
                return DaemonStop.KILLED
            return DaemonStop.SURVIVED
    except (ProcessLookupError, psutil.NoSuchProcess):
        return DaemonStop.ALREADY_GONE


def signal_own_session_child(process: SpawnedChild, sig: int) -> None:
    """Send ``sig`` to the process group led by ``process``, a child we spawned.

    ``process`` must be a ``subprocess.Popen`` started with
    ``start_new_session=True``: it must still be running and unreaped (so its
    pid is still ours) and must lead its own group, which is never init's or
    ours. A mock is refused: its ``pid`` is not a plain int, and its ``poll()``
    returns neither None nor an exit status.

    Raises:
        RefusedSignalTarget: ``process`` has no plain pid, answers ``poll()``
            with something other than None or an int, or does not lead a group
            of its own.
        ProcessLookupError: The child has already exited.
    """
    pid = _plain_pid(process.pid)
    status = process.poll()
    if status is not None:
        if type(status) is not int:
            raise RefusedSignalTarget(
                f"{process!r} is not a subprocess.Popen: poll() -> {status!r}"
            )
        raise ProcessLookupError(f"child pid {pid} has already exited with {status}")
    _refuse_own_lineage(pid)
    group = os.getpgid(pid)
    if group != pid:
        raise RefusedSignalTarget(
            f"child pid {pid} does not lead its own group (group {group}); "
            "start it with start_new_session=True"
        )
    if group == os.getpgid(0):
        raise RefusedSignalTarget(f"group {group} is this process's own group")
    os.killpg(group, sig)
