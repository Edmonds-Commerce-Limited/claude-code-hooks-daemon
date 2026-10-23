"""Repair an unusable relay binary in the background, once per cause (Plan 00529 Task 2c).

``relay_binary_checker`` finds, at session start, that the configured relay
binary is missing or cannot run. Hooks then fall through to the bash path,
loudly. This module starts the ``transport on`` provisioning without the toggle
(``ensure_relay_binary`` plus forwarder regeneration) DETACHED from the hook,
because a build can take minutes and the session-start answer must not wait.

Modelled on ``background_sync``:

- One state file per cause, keyed by binary path, defect and daemon version.
  Creating it (``O_EXCL``) is the claim, so a cause is attempted at most once,
  however many sessions start. A failed attempt stays failed and is reported at
  every session start until ``transport on`` is run by hand.
- The child holds a lock while it works, so two repairs never build at once.
- The state files use ``background_sync``'s ``key=value`` format and are read by
  its reader. A finished repair is ``synced``.

Nothing here is silent: a spawn that fails, a provisioning failure, a binary
still unusable afterwards and an exception are all recorded as ``failed`` with
their reason, and the checker reports that record.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import logging
import os
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from claude_code_hooks_daemon.install.background_sync import (
    SyncRecord,
    SyncStatus,
    read_state_file,
)
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

if TYPE_CHECKING:
    from claude_code_hooks_daemon.install.transport_toggle import RelayProvision

logger = logging.getLogger(__name__)

#: Under the daemon's untracked directory, beside ``background-sync``.
REPAIR_STATE_DIR_NAME: Final[str] = "relay-repair"

#: The module the detached child runs (``python -m``).
REPAIR_MODULE: Final[str] = "claude_code_hooks_daemon.install.relay_repair"

REPAIR_FAILED_EXIT_CODE: Final[int] = 1

_LOCK_NAME: Final[str] = "repair.lock"
#: Held only for the instant of a state write, never across the repair's work.
_STATE_LOCK_NAME: Final[str] = "state.lock"
_STATE_SUFFIX: Final[str] = ".state"
_LOG_SUFFIX: Final[str] = ".log"
_KEY_HEX_CHARS: Final[int] = 16
_FILE_MODE: Final[int] = 0o644

#: Starts ``argv`` detached with its output in the log; returns its pid.
SpawnFn = Callable[[list[str], Path], int]


@dataclass(frozen=True)
class RepairNotice:
    """What :func:`start_relay_repair` did about one cause.

    ``started``: this call launched the repair. ``record``: the cause was
    already claimed, and this is what its attempt recorded. ``failure``: the
    repair could not be started, and why.
    """

    started: bool
    record: SyncRecord | None
    failure: str | None
    state_path: Path
    log_path: Path


def cause_key(binary: Path, defect: str, version: str) -> str:
    """A filename-safe key for one cause: this binary, this defect, this daemon version."""
    digest = hashlib.sha256(f"{binary}\0{defect}\0{version}".encode()).hexdigest()
    return digest[:_KEY_HEX_CHARS]


def repair_state_path(untracked_dir: Path, key: str) -> Path:
    """The state file of the repair of cause ``key``."""
    return untracked_dir / REPAIR_STATE_DIR_NAME / f"{key}{_STATE_SUFFIX}"


def repair_log_path(untracked_dir: Path, key: str) -> Path:
    """The log the repair of cause ``key`` writes its output to."""
    return untracked_dir / REPAIR_STATE_DIR_NAME / f"{key}{_LOG_SUFFIX}"


def repair_lock_path(untracked_dir: Path) -> Path:
    """The lock every repair holds while it works."""
    return untracked_dir / REPAIR_STATE_DIR_NAME / _LOCK_NAME


def _state_text(status: SyncStatus, *, detail: str, pid: int | None = None) -> str:
    lines = [f"status={status.value}"]
    if pid is not None:
        lines.append(f"pid={pid}")
    # The format is one key per line, so a multi-line reason is folded.
    lines.append("detail=" + " ".join(detail.split()))
    return "\n".join(lines) + "\n"


def _state_lock(path: Path) -> Path:
    return path.parent / _STATE_LOCK_NAME


def _write_state(path: Path, status: SyncStatus, *, detail: str, pid: int | None = None) -> None:
    """Replace the state file atomically, so a reader never sees half of it.

    Every write holds the state lock, so the starter's pid record and the
    child's own records never interleave.
    """
    with _exclusive(_state_lock(path)):
        _replace_state(path, _state_text(status, detail=detail, pid=pid))


def _replace_state(path: Path, text: str) -> None:
    tmp = unique_temp_path(path)
    tmp.write_text(text)
    tmp.replace(path)


def _record_spawned_pid(path: Path, claim: str, pid: int, *, detail: str) -> None:
    """Put the child's pid on the claim, unless the child has written its own record.

    Without a pid a dead child is indistinguishable from a live one. A child
    that already recorded anything wrote its own pid, and a finished one wrote
    its result, which must not be put back to running.
    """
    with _exclusive(_state_lock(path)):
        if path.read_text() == claim:
            _replace_state(path, _state_text(SyncStatus.RUNNING, detail=detail, pid=pid))


def _reap(pid: int) -> None:
    """Wait for the child so it never lingers as a zombie.

    A ChildProcessError (someone else reaped it) is left to raise: the thread's
    excepthook reports it.
    """
    _, status = os.waitpid(pid, 0)
    logger.info("relay repair child %d exited (%d)", pid, os.waitstatus_to_exitcode(status))


def spawn_detached(argv: list[str], log: Path) -> int:
    """Start ``argv`` in a new session, stdin from /dev/null, stdout and stderr to ``log``.

    No shell and no PATH search: ``argv[0]`` must be a path. The caller does not
    wait; a daemon thread reaps the child, which otherwise stays a zombie for the
    caller's lifetime and still answers ``kill(pid, 0)``. Raises OSError when the
    program cannot be started.
    """
    file_actions = [
        (os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0),
        (os.POSIX_SPAWN_OPEN, 1, str(log), os.O_WRONLY | os.O_CREAT | os.O_APPEND, _FILE_MODE),
        (os.POSIX_SPAWN_DUP2, 1, 2),
    ]
    pid = os.posix_spawn(argv[0], argv, os.environ, file_actions=file_actions, setsid=True)
    threading.Thread(
        target=_reap, args=(pid,), name=f"relay-repair-reap-{pid}", daemon=True
    ).start()
    return pid


def start_relay_repair(
    project_root: Path,
    binary: Path,
    defect: str,
    *,
    untracked_dir: Path,
    version: str,
    spawn_fn: SpawnFn = spawn_detached,
) -> RepairNotice:
    """Start the detached repair of this cause, unless it was already attempted.

    Never raises for an OSError and never waits for the repair: the caller is
    a session-start hook. A failure to start is returned and recorded.
    """
    key = cause_key(binary, defect, version)
    state = repair_state_path(untracked_dir, key)
    log = repair_log_path(untracked_dir, key)

    def notice(
        *, started: bool = False, record: SyncRecord | None = None, failure: str | None = None
    ) -> RepairNotice:
        return RepairNotice(started, record, failure, state, log)

    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(state, os.O_CREAT | os.O_EXCL | os.O_WRONLY, _FILE_MODE)
    except FileExistsError:
        return notice(record=read_state_file(state, log))
    except OSError as exc:
        return notice(failure=f"the repair state file {state} cannot be created ({exc})")
    detail = f"repairing {binary} ({defect}), starting"
    claim = _state_text(SyncStatus.RUNNING, detail=detail)
    with os.fdopen(fd, "w") as handle:
        handle.write(claim)

    argv = [
        sys.executable,
        "-m",
        REPAIR_MODULE,
        "--project-root",
        str(project_root),
        "--binary",
        str(binary),
        "--state",
        str(state),
    ]
    try:
        pid = spawn_fn(argv, log)
    except OSError as exc:
        failure = f"the background repair could not be started ({exc})"
        logger.error("relay repair of %s not started: %s", binary, exc)
        _write_state(state, SyncStatus.FAILED, detail=failure)
        return notice(failure=failure)
    try:
        _record_spawned_pid(state, claim, pid, detail=detail)
    except OSError as exc:
        # The repair is running; only its pid is unrecorded. Reported, and the
        # reader fails a pid-less claim once its grace has passed.
        return notice(
            started=True,
            failure=(
                f"the background repair started (pid {pid}) but its pid could not be "
                f"recorded in {state} ({exc})"
            ),
        )
    return notice(started=True)


@contextmanager
def _exclusive(lock: Path) -> Iterator[None]:
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def run_relay_repair(
    binary: Path,
    state: Path,
    lock: Path,
    *,
    provision_fn: Callable[[], RelayProvision],
    regenerate_fn: Callable[[], list[str]],
    defect_fn: Callable[[Path], str | None],
) -> int:
    """The detached child's work: provision, regenerate, confirm, record.

    Returns 0 when the binary is usable afterwards, else
    :data:`REPAIR_FAILED_EXIT_CODE`. An exception is recorded as ``failed`` and
    re-raised, so the log carries its traceback too.
    """
    pid = os.getpid()
    _write_state(state, SyncStatus.RUNNING, pid=pid, detail=f"repairing {binary}")
    try:
        with _exclusive(lock):
            if defect_fn(binary) is None:
                _write_state(
                    state,
                    SyncStatus.SYNCED,
                    pid=pid,
                    detail=f"{binary} was already usable when the repair took the lock",
                )
                return 0
            provisioned = provision_fn()
            if provisioned.failure is not None:
                _write_state(state, SyncStatus.FAILED, pid=pid, detail=provisioned.failure)
                return REPAIR_FAILED_EXIT_CODE
            rewritten = regenerate_fn()
            remaining = defect_fn(binary)
            if remaining is not None:
                _write_state(
                    state,
                    SyncStatus.FAILED,
                    pid=pid,
                    detail=f"{binary} is still {remaining} after provisioning",
                )
                return REPAIR_FAILED_EXIT_CODE
            route = provisioned.route or "already in place"
            forwarders = ", ".join(rewritten) or "none"
            _write_state(
                state,
                SyncStatus.SYNCED,
                pid=pid,
                detail=f"{binary} provisioned ({route}); forwarders rewritten: {forwarders}",
            )
            return 0
    except Exception as exc:
        _write_state(state, SyncStatus.FAILED, pid=pid, detail=f"{type(exc).__name__}: {exc}")
        logger.exception("relay repair of %s raised", binary)
        raise


def main(argv: list[str] | None = None) -> int:
    """Entry point of the detached child started by :func:`start_relay_repair`."""
    parser = argparse.ArgumentParser(prog=f"python -m {REPAIR_MODULE}")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from claude_code_hooks_daemon.install.forwarder_generator import regenerate_deployed_hooks
    from claude_code_hooks_daemon.install.relay_deploy import relay_binary_defect
    from claude_code_hooks_daemon.install.transport_toggle import ensure_relay_binary

    root: Path = args.project_root
    return run_relay_repair(
        args.binary,
        args.state,
        args.state.parent / _LOCK_NAME,
        provision_fn=lambda: ensure_relay_binary(root),
        regenerate_fn=lambda: regenerate_deployed_hooks(root, root / ".claude" / "hooks"),
        defect_fn=relay_binary_defect,
    )


if __name__ == "__main__":
    sys.exit(main())
