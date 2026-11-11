"""Write ``git config`` while waiting out ``config.lock`` (Plan 00474 N621).

Git takes ``.git/config.lock`` for every config write and does not retry when it
is held, so two parallel agents writing the one shared config file made one of
them fail at once. A write here retries on that one failure for a bounded,
load-scaled wait, then raises :class:`GitConfigLockError` naming the lock path.
A lock older than a minute with no git process running is reported as stale; it
is never deleted here, because a lock a live process holds must not be removed.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.load_scaling import describe_load, scaled_timeout

_LOCK_MESSAGE: Final[str] = "could not lock config file"
_LOCK_PATH_PATTERN: Final[re.Pattern[str]] = re.compile(r"could not lock config file (.+?): ")
_LOCK_SUFFIX: Final[str] = ".lock"
_PROC_ROOT: Final[Path] = Path("/proc")
_GIT_PROCESS_NAME: Final[str] = "git"


class GitConfigLockError(RuntimeError):
    """``config.lock`` stayed held for the whole wait; ``lock_path`` names it."""

    def __init__(self, message: str, lock_path: Path | None) -> None:
        super().__init__(message)
        self.lock_path = lock_path


def _git_process_running() -> bool | None:
    """Whether any process named ``git`` runs; ``None`` when the host cannot say."""
    if not _PROC_ROOT.is_dir():
        return None
    return any(_is_git_process(entry) for entry in _PROC_ROOT.iterdir() if entry.name.isdigit())


def _is_git_process(proc_entry: Path) -> bool:
    """Whether ``/proc/<pid>`` is a git process; one that ended meanwhile is not."""
    try:
        return (proc_entry / "comm").read_text().strip() == _GIT_PROCESS_NAME
    except OSError:
        return False


def _lock_path(repo: Path, stderr: str) -> Path | None:
    """The lock file git names: it reports the config file (possibly relative to ``repo``)."""
    match = _LOCK_PATH_PATTERN.search(stderr)
    if match is None:
        return None
    return repo / f"{match.group(1)}{_LOCK_SUFFIX}"


def _stale_note(lock: Path | None) -> str:
    """A sentence calling the lock stale, or an empty string when it is not provably so."""
    if lock is None:
        return ""
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return ""
    if age < Timeout.GIT_CONFIG_LOCK_STALE_AGE or _git_process_running() is not False:
        return ""
    return (
        f" The lock is stale: {int(age)}s old and no git process is running. "
        f"Once you are sure nothing is writing the config, remove it with: rm {lock}"
    )


def run_git_config_write(
    repo: Path,
    *args: str,
    base_wait: float | None = None,
    ceiling: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``git config <args>``, retrying while ``config.lock`` is held.

    Any other failure is returned as-is for the caller to judge. The wait
    defaults to the ``Timeout.GIT_CONFIG_LOCK_WAIT`` pair, read at call time.

    Raises:
        GitConfigLockError: If the lock is still held after the load-scaled wait.
    """
    wait = scaled_timeout(
        Timeout.GIT_CONFIG_LOCK_WAIT if base_wait is None else base_wait,
        Timeout.GIT_CONFIG_LOCK_WAIT_MAX if ceiling is None else ceiling,
    )
    deadline = time.monotonic() + wait
    while True:
        result = run_git(repo, "config", *args)
        if result.returncode == 0 or _LOCK_MESSAGE not in result.stderr:
            return result
        if time.monotonic() >= deadline:
            lock = _lock_path(repo, result.stderr)
            raise GitConfigLockError(
                f"git config write blocked: {lock or 'config.lock'} stayed held for "
                f"{wait:.1f}s ({describe_load()}).{_stale_note(lock)}",
                lock,
            )
        time.sleep(Timeout.GIT_CONFIG_LOCK_POLL)
