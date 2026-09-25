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
import logging
import os
import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

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
    `subprocess` closes every descriptor above stderr by default, AND
    `open_lock_fd`'s `os.open()` itself returns a non-inheritable descriptor
    (PEP 446's Python 3.4+ default), so this step is required, not optional.
    `pass_fds` clears `FD_CLOEXEC` for exactly the fds it lists before that
    child's own exec, so from THAT POINT ON the descriptor behaves like an
    ordinary, non-CLOEXEC one: a shell child spawned this way (bash,
    `run_tests.sh`'s own `exec {FD}>>`) passes it to every further child of
    ITS OWN for free, with no further `pass_fds` needed at that level. A
    caller that instead `os.execve`s directly, replacing this process,
    must call `os.set_inheritable(fd, True)` itself first -- `pass_fds`
    only helps a `subprocess`-spawned child.

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

    Review 10 B2: checking "is an inherited fd open on the lock path" and
    then, separately, "does a FRESH probe find the file locked" proves only
    that SOMEONE, somewhere, holds it -- an evader that inherits an UNLOCKED
    fd to the lock path passes that check for free whenever a genuinely
    legitimate run happens to be holding the lock concurrently, even though
    the evader's own run is not serialised against it at all.

    The proof must instead be that THIS inherited descriptor -- the exact
    open file description a legitimate caller's `acquire_full_qa_lock`
    flocked before `exec`ing this process's ancestry -- holds the lock.
    `flock` locks are a property of the OPEN FILE DESCRIPTION, not the
    process or the fd number, and `fork`/`exec` share that description with
    every descendant that does not close it. So calling
    `flock(fd, LOCK_EX | LOCK_NB)` directly on each candidate inherited fd is
    decisive:

    - If the description already holds the lock (the common case -- an
      ancestor acquired it before `exec`), re-requesting the same mode on the
      same description is a no-op that returns immediately.
    - If nobody holds it, this call GRANTS the lock via that very
      descriptor -- which is not a bug: an inherited fd genuinely proves
      ancestry from the acquiring code path, so holding it from here on is
      exactly the serialisation the lock exists to provide.
    - If a DIFFERENT open file description (this process's own fresh `open`,
      or another process entirely) already holds it exclusively, the call
      raises `BlockingIOError` -- this descriptor is not the one holding it,
      so this candidate proves nothing, no matter who else does hold it.

    Anything this cannot establish -- `/proc` unavailable, no candidate
    fd resolves to the lock path -- is read as NOT held. This is a security
    caller: a missing answer must never be mistaken for a granted one.
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

    skipped_unresolvable = 0
    skipped_not_the_holder = 0
    for entry in candidates:
        try:
            target = entry.readlink()
        except OSError:
            # /proc/self/fd is inherently racy against THIS process's own
            # fds opening and closing between the listdir above and this
            # readlink -- not resolving one candidate is not evidence about
            # the lock, so keep scanning the rest. Counted, not silently
            # dropped, so a caller logging the summary below can see it.
            skipped_unresolvable += 1
            continue
        if target != lock_path:
            continue
        try:
            fd = int(entry.name)
        except ValueError:
            # /proc/self/fd entries are always numeric; this would mean the
            # directory listing no longer matches what it reports.
            skipped_unresolvable += 1
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Someone else's open file description holds it exclusively --
            # this candidate is not the holder. Keep scanning: a different
            # inherited fd may still be the genuine one.
            skipped_not_the_holder += 1
            continue
        else:
            # Review 10 m1: mark it CLOEXEC now that possession is PROVEN, so
            # a further descendant of THIS process (a test fixture that
            # backgrounds an orphan, review 10's H repro) does not silently
            # inherit it onward and leak the lock past this process's own
            # exit. Set only after the proof, not before: pytest itself
            # still needs the ordinary, non-CLOEXEC inheritance across
            # fork/exec to have carried the fd this far.
            fcntl.fcntl(fd, fcntl.F_SETFD, fcntl.fcntl(fd, fcntl.F_GETFD) | fcntl.FD_CLOEXEC)
            return True
    if skipped_unresolvable or skipped_not_the_holder:
        logger.debug(
            "full_qa_lock_is_held(%s): no inherited fd proved possession "
            "(%d unresolvable, %d resolved but not the holder)",
            lock_path,
            skipped_unresolvable,
            skipped_not_the_holder,
        )
    return False
