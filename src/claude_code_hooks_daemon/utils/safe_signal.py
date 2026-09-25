"""The one place a nonzero signal is sent to another process (Plan 00466 N59).

A signal is only as safe as the proof that its pid names the intended process.
Twice a unit test killed the whole container: a ``MagicMock`` Popen's pid
coerces to 1, and ``os.killpg(os.getpgid(1), SIGKILL)`` took out init. A PID
file is no better a proof, because PID files survive a container restart and a
restarted container reuses small pids, so a stale file can name Claude Code.

Every nonzero signal this project sends therefore goes through one of two
proofs, and ``scripts/qa/check_signal_targets.py`` fails QA on one that does
not:

* :func:`signal_verified_daemon` / :func:`verified_daemon_process` — the pid's
  command line is a daemon SERVER for THIS project root, not merely any daemon.
* :func:`signal_verified_daemon_via_pidfd` — the same proof, delivered via
  ``os.pidfd_open``/``signal.pidfd_send_signal`` instead of ``psutil``, so a
  pid reused between the proof and the send still cannot receive the signal.
* :func:`signal_own_session_child` — a group kill, only to a child this code
  spawned with ``start_new_session=True`` that is still running and still
  leads its own group.

Both refuse a pid that is not a plain ``int`` above 1 (a ``bool`` and a
``MagicMock`` both coerce to 1), this process, any ancestor, and this
process's own group. A refusal raises :class:`RefusedSignalTarget`; security
callers fail closed, so a pid whose identity cannot be read is refused too.
"""

from __future__ import annotations

import os
import signal
from enum import Enum
from pathlib import Path
from typing import Protocol

import psutil

from claude_code_hooks_daemon.daemon.process_verification import (
    _extract_project_root,
    _is_daemon_server_process,
    _normalize_root,
)

#: Init's pid and the group it leads; never a target.
_INIT_PID = 1


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


def verified_daemon_process(pid: object, *, project_root: Path | str) -> psutil.Process:
    """A handle on ``pid``, proven to be the daemon server for ``project_root``.

    The returned :class:`psutil.Process` remembers the process's start time and
    re-checks it before every ``send_signal``/``terminate``/``kill``, so a pid
    reused after this check is refused rather than signalled.

    Raises:
        RefusedSignalTarget: ``pid`` is not a plain int above 1, is this
            process or an ancestor, is not a daemon server, serves another
            project root, or cannot be inspected.
        ProcessLookupError: No process has this pid.
    """
    checked = _plain_pid(pid)
    _refuse_own_lineage(checked)
    try:
        process = psutil.Process(checked)
        cmdline = process.cmdline()
    except psutil.NoSuchProcess as gone:
        raise ProcessLookupError(f"no process has pid {checked}") from gone
    except psutil.AccessDenied as denied:
        raise RefusedSignalTarget(f"cannot read the command line of pid {checked}") from denied

    if not _is_daemon_server_process(cmdline):
        raise RefusedSignalTarget(f"pid {checked} is not a daemon server: {cmdline!r}")
    expected = _normalize_root(Path(project_root).absolute())
    actual = _extract_project_root(process)
    if actual != expected:
        raise RefusedSignalTarget(
            f"pid {checked} is a daemon for project root {actual!r}, not {expected!r}"
        )
    return process


def signal_verified_daemon(pid: object, sig: int, *, project_root: Path | str) -> None:
    """Send ``sig`` to ``pid`` only once it is proven to be this project's daemon.

    Raises:
        RefusedSignalTarget: See :func:`verified_daemon_process`.
        ProcessLookupError: The process is gone, or its pid was reused.
        PermissionError: This process may not signal it.
    """
    process = verified_daemon_process(pid, project_root=project_root)
    try:
        process.send_signal(sig)
    except psutil.NoSuchProcess as gone:
        raise ProcessLookupError(f"daemon pid {process.pid} has exited") from gone
    except psutil.AccessDenied as denied:
        raise PermissionError(f"not permitted to signal daemon pid {process.pid}") from denied


def signal_verified_daemon_via_pidfd(pid: object, sig: int, *, project_root: Path | str) -> None:
    """Send ``sig`` to ``pid`` via a pidfd, only once proven this project's daemon.

    The identity proof is identical to :func:`signal_verified_daemon`; only the
    delivery syscall differs. A pidfd is immune to pid reuse mid-flight: once
    opened it is bound to the exact process the proof verified, so a pid
    reused by something else between the proof and the send still cannot
    receive this signal -- ``pidfd_send_signal`` reports
    :class:`ProcessLookupError` instead. Linux-only (``os.pidfd_open``,
    Python 3.9+); there is no fallback here, so a caller that must run
    elsewhere should use :func:`signal_verified_daemon`.

    Raises:
        RefusedSignalTarget: See :func:`verified_daemon_process`.
        ProcessLookupError: The process is gone, or exited between the proof
            and the send.
        PermissionError: This process may not signal it.
    """
    process = verified_daemon_process(pid, project_root=project_root)
    pidfd = os.pidfd_open(process.pid)
    try:
        signal.pidfd_send_signal(pidfd, sig)
    finally:
        os.close(pidfd)


class DaemonStop(Enum):
    """How :func:`stop_verified_daemon` left the daemon."""

    TERMINATED = "terminated"
    KILLED = "killed"
    ALREADY_GONE = "already_gone"
    SURVIVED = "survived"


def stop_verified_daemon(
    pid: object, *, project_root: Path | str, grace_seconds: float
) -> DaemonStop:
    """SIGTERM this project's daemon at ``pid``, then SIGKILL it after the grace.

    The identity is proven once, and the handle's start-time check stops a pid
    reused during the grace from receiving the SIGKILL.

    Raises:
        RefusedSignalTarget: See :func:`verified_daemon_process`.
        PermissionError: This process may not signal it.
    """
    try:
        process = verified_daemon_process(pid, project_root=project_root)
    except ProcessLookupError:
        return DaemonStop.ALREADY_GONE
    try:
        process.terminate()
        try:
            process.wait(timeout=grace_seconds)
            return DaemonStop.TERMINATED
        except psutil.TimeoutExpired:
            process.kill()
        try:
            process.wait(timeout=grace_seconds)
            return DaemonStop.KILLED
        except psutil.TimeoutExpired:
            return DaemonStop.SURVIVED
    except psutil.NoSuchProcess:
        return DaemonStop.ALREADY_GONE
    except psutil.AccessDenied as denied:
        raise PermissionError(f"not permitted to signal daemon pid {process.pid}") from denied


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
