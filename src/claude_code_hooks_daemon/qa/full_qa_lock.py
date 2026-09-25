"""The host-wide full-QA lock: the sink-side backstop (Plan 00463 round 9).

Nine reviews of the sub-agent full-QA blocker chased command-TEXT evasions --
perl, node, `at`, `systemd-run`, substitution-built paths, oversized text, and
more -- and review 9 still found 81 of 202 evasion rows allowed. A Bash-text
denylist can never close that set: any program can start a whole-suite test
run, so no finite pattern list enumerates every launcher.

So the guarantee moves to the SINK -- the place every route ends up, whatever
launched it: pytest itself. `tests/conftest.py` refuses to run a
whole-suite-sized selection unless this lock is held. The handler
(`subagent_full_qa_blocker`) stays as the friendly, fast first line that
denies the common shapes early with a helpful message; this lock is what makes
the refusal true when the handler is evaded.

**"Holds the lock" is PROVEN, never claimed.** A child (a worker, a test
process spawned by `llm_qa.py` or `run_tests.sh`) proves possession by an
INHERITED file descriptor pointing at this exact lock file -- checked via
`/proc/self/fd` -- confirmed by flock semantics: a fresh probe descriptor on
the same path finds it already exclusively locked. An environment variable
alone proves nothing, because any evasion could set one for itself; this
module never reads one to decide possession.

**Lives under the git COMMON dir, not any one worktree.** `git worktree`
checkouts share one `.git` (the common dir lives at the main checkout, and
`git rev-parse --git-common-dir` resolves to it from every worktree), so a
lock keyed there is the same lock file no matter which worktree the run
started in -- which is the whole point: the coordinator's gate and a
sub-agent's evasion in a DIFFERENT worktree must contend for the SAME lock.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

#: Not `/tmp` (security standard B108: never a world-writable shared
#: directory) and not `untracked/` of any one worktree (a worktree's
#: `untracked/` is exactly what this lock must be visible ACROSS).
LOCK_FILE_NAME = "hooksdaemon-full-qa.lock"
_LOCK_FILE_MODE = 0o644


def git_common_dir(project_root: Path) -> Path:
    """The directory every worktree of this repository shares.

    Raises:
        subprocess.CalledProcessError: `project_root` is not inside a git
            worktree -- there is no shared lock location to compute.
    """
    result = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


def host_lock_path(project_root: Path) -> Path:
    """The one lock file shared by every worktree of this repository."""
    return git_common_dir(project_root) / LOCK_FILE_NAME


def open_lock_fd(project_root: Path) -> int:
    """Open (creating if needed) the lock file; caller owns the descriptor.

    A raw descriptor, not a buffered handle: `flock` operates on a file
    DESCRIPTOR, and the whole design depends on that descriptor being the
    thing a child process inherits.
    """
    path = host_lock_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(path, os.O_RDWR | os.O_CREAT, _LOCK_FILE_MODE)


@contextmanager
def acquire_full_qa_lock(project_root: Path, *, blocking: bool = True) -> Generator[int]:
    """Hold the host-wide full-QA lock for the block's duration.

    The descriptor is yielded so a caller that launches Python subprocesses
    can pass it explicitly (`subprocess.run(..., pass_fds=(fd,))`) --
    `subprocess` closes every descriptor above stderr by default. A caller
    that instead `exec`s a shell command (bash, `os.execve`) needs no such
    step: an ordinary descriptor without `FD_CLOEXEC` survives exec and is
    inherited by every further child of that shell for free.

    Args:
        project_root: any checkout (main or worktree) of this repository.
        blocking: wait for the lock (the default) or raise `BlockingIOError`
            immediately when another holder has it.

    Raises:
        BlockingIOError: `blocking=False` and the lock is already held.
    """
    fd = open_lock_fd(project_root)
    try:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.flock(fd, flags)
        yield fd
    finally:
        os.close(fd)


def full_qa_lock_is_held(project_root: Path) -> bool:
    """Whether THIS process can prove an ancestor holds the host-wide lock.

    Two things must both be true, in order -- either alone is not proof:

    1. One of this process's own open descriptors resolves (via
       `/proc/self/fd`) to the exact lock file. A descriptor got here only by
       inheritance across `fork`/`exec`, which is not something an evasion can
       fake by setting a variable.
    2. `flock` genuinely reports the file as exclusively locked, checked from
       a FRESH descriptor opened just for the probe -- inheriting a CLOSED or
       merely-open-but-unlocked descriptor proves nothing.

    Anything this cannot establish -- `/proc` unavailable, the probe open
    itself failing -- is read as NOT held. This is a security caller: a
    missing answer must never be mistaken for a granted one.
    """
    try:
        lock_path = host_lock_path(project_root).resolve()
    except (OSError, subprocess.CalledProcessError):
        return False

    fd_dir = Path("/proc/self/fd")
    try:
        candidates = list(fd_dir.iterdir())
    except OSError:
        return False

    inherited = False
    unreadable = 0
    for entry in candidates:
        try:
            target = entry.readlink()
        except OSError:
            # /proc/self/fd is inherently racy against THIS process's own
            # fds opening and closing between the listdir above and this
            # readlink -- not resolving one candidate is not evidence about
            # the lock, so keep scanning. Counted, not silently dropped: a
            # persistently high count would show up in a caller that reports it.
            unreadable += 1
            continue
        if target == lock_path:
            inherited = True
            break
    if not inherited:
        # Covers both "no fd matched" and "some candidates raced away
        # unread" (unreadable > 0) -- either way there is no proof, and an
        # inconclusive scan is read the same as a negative one (fail closed).
        return False

    try:
        probe_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, _LOCK_FILE_MODE)
    except OSError:
        return False
    try:
        fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        fcntl.flock(probe_fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(probe_fd)
