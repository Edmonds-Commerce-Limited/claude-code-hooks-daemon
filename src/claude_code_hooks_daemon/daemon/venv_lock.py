"""The venv build lock, Python side (Plan 00100 Phase 4).

``scripts/install/venv.sh::ensure_venv`` serialises venv creation and rebuild
on ``{project_root}/untracked/.venv-bootstrap.lock`` so two daemons starting
at once build the venv once and share it. ``hooks-daemon repair`` runs
``uv sync`` into that same venv, so it must contend on the SAME lock, with
the same file and the same backend choice — otherwise the bash lock only
protects bash from bash.

Contract (mirrors the bash implementation exactly):

- ``flock`` backend (default): ``flock(2)`` on the lock file. Task 4.0's
  spike showed it excludes across processes sharing a Podman bind mount.
- ``mkdir`` backend: ``.venv-bootstrap.lock.d`` with a ``pid`` file inside;
  a lock dir older than ``HOOKS_DAEMON_VENV_LOCK_STALE_SECONDS`` (600) is
  presumed abandoned and reclaimed.
- ``HOOKS_DAEMON_VENV_LOCK_BACKEND`` forces one backend; anything else is a
  ``ValueError``.
- ``HOOKS_DAEMON_VENV_LOCK_TIMEOUT`` (120) bounds the wait; on expiry
  ``VenvLockTimeout`` names the lock path and the bound.

Stdlib only — this is imported by the CLI, which may run before any venv
exists.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

VENV_LOCK_FILE_NAME = ".venv-bootstrap.lock"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_STALE_SECONDS = 600

_BACKEND_ENV = "HOOKS_DAEMON_VENV_LOCK_BACKEND"
_TIMEOUT_ENV = "HOOKS_DAEMON_VENV_LOCK_TIMEOUT"
_STALE_ENV = "HOOKS_DAEMON_VENV_LOCK_STALE_SECONDS"
_KNOWN_BACKENDS = ("flock", "mkdir")
_POLL_SECONDS = 0.2


class VenvLockTimeout(RuntimeError):
    """The venv build lock stayed held for the whole wait bound."""


def venv_lock_path(project_root: Path) -> Path:
    """The flock file; the mkdir backend uses ``<this>.d``."""
    return project_root / "untracked" / VENV_LOCK_FILE_NAME


def _select_backend(backend: str | None) -> str:
    chosen = backend if backend is not None else os.environ.get(_BACKEND_ENV, "")
    if not chosen:
        chosen = "flock" if shutil.which("flock") else "mkdir"
    if chosen not in _KNOWN_BACKENDS:
        raise ValueError(
            f"{_BACKEND_ENV} must be one of {', '.join(_KNOWN_BACKENDS)}; got {chosen!r}"
        )
    return chosen


def _env_seconds(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number of seconds; got {raw!r}") from exc


def _timeout_message(lock_path: Path, timeout_seconds: float) -> str:
    return (
        f"gave up waiting for the venv lock after {timeout_seconds:g}s: {lock_path}. "
        "Another daemon start or 'hooks-daemon repair' is still building the venv, "
        "or its holder died. Retry once it has finished."
    )


def _wait_message(lock_path: Path, timeout_seconds: float) -> str:
    return (
        f"another process holds the venv lock ({lock_path}) — "
        f"waiting up to {timeout_seconds:g}s for its build to finish"
    )


@contextmanager
def _flock(
    lock_file: Path, timeout_seconds: float, on_wait: Callable[[str], None] | None
) -> Iterator[None]:
    deadline = time.monotonic() + timeout_seconds
    announced = False
    with lock_file.open("a") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not announced:
                    announced = True
                    if on_wait is not None:
                        on_wait(_wait_message(lock_file, timeout_seconds))
                if time.monotonic() >= deadline:
                    raise VenvLockTimeout(_timeout_message(lock_file, timeout_seconds)) from None
                time.sleep(_POLL_SECONDS)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _mkdir_lock(
    lock_dir: Path, timeout_seconds: float, on_wait: Callable[[str], None] | None
) -> Iterator[None]:
    stale_seconds = _env_seconds(_STALE_ENV, DEFAULT_STALE_SECONDS)
    deadline = time.monotonic() + timeout_seconds
    announced = False
    retaken_immediately = False
    while True:
        try:
            lock_dir.mkdir()
            break
        except FileExistsError:
            try:
                age = time.time() - lock_dir.stat().st_mtime
            except FileNotFoundError:
                # The holder's rmtree landed between our mkdir and this stat --
                # the contention window this lock exists for. The lock is free,
                # so retake it. Letting the error out would surface a lock-layer
                # fault as whatever the caller's FileNotFoundError handler says.
                #
                # Bounded like every other wait here: a lock NAME that can never
                # be stat'ed (a dangling symlink) must end in the timeout rather
                # than spin, so only the first retry is immediate.
                if time.monotonic() >= deadline:
                    raise VenvLockTimeout(_timeout_message(lock_dir, timeout_seconds)) from None
                if retaken_immediately:
                    time.sleep(_POLL_SECONDS)
                retaken_immediately = True
                continue
            if age >= stale_seconds:
                if on_wait is not None:
                    on_wait(
                        f"removing stale venv lock {lock_dir} "
                        f"({age:.0f}s old, its holder is presumed dead)"
                    )
                shutil.rmtree(lock_dir, ignore_errors=True)
                continue
            if not announced:
                announced = True
                if on_wait is not None:
                    on_wait(_wait_message(lock_dir, timeout_seconds))
            if time.monotonic() >= deadline:
                raise VenvLockTimeout(_timeout_message(lock_dir, timeout_seconds)) from None
            time.sleep(_POLL_SECONDS)
    (lock_dir / "pid").write_text(f"{os.getpid()}\n")
    try:
        yield
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)


@contextmanager
def venv_lock(
    project_root: Path,
    timeout_seconds: float | None = None,
    *,
    backend: str | None = None,
    on_wait: Callable[[str], None] | None = None,
) -> Iterator[None]:
    """Hold the venv build lock for ``project_root`` for the body's duration.

    Args:
        project_root: the daemon directory whose ``untracked/`` holds the venvs.
        timeout_seconds: wait bound; ``None`` reads ``HOOKS_DAEMON_VENV_LOCK_TIMEOUT``
            and falls back to :data:`DEFAULT_TIMEOUT_SECONDS`.
        backend: ``"flock"`` or ``"mkdir"``; ``None`` reads
            ``HOOKS_DAEMON_VENV_LOCK_BACKEND`` and defaults to flock where installed.
        on_wait: receives each user-facing notice (waiting, stale reclaim) so the
            caller decides where it is printed.

    Raises:
        VenvLockTimeout: the lock stayed held past the bound.
        ValueError: an unrecognised backend or a non-numeric timeout.
    """
    chosen = _select_backend(backend)
    bound = (
        timeout_seconds
        if timeout_seconds is not None
        else _env_seconds(_TIMEOUT_ENV, DEFAULT_TIMEOUT_SECONDS)
    )
    lock_file = venv_lock_path(project_root)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    if chosen == "flock":
        with _flock(lock_file, bound, on_wait):
            yield
        return
    with _mkdir_lock(lock_file.with_name(lock_file.name + ".d"), bound, on_wait):
        yield
