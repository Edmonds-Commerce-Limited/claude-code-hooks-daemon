"""Read-only detection of stale git worktrees and stale daemons (Plan 00470 Task 4.2).

An always-on session accumulates both. A worktree outlives the work it was cut
for, and a daemon outlives the checkout it served. Neither costs anything
visible until someone has to find the live one among the dead ones.

Everything here is REPORT-FIRST: it asks git, ``/proc`` and the filesystem
questions and removes nothing. Each finding carries the exact command a human
or agent MAY choose to run, and nothing in this module runs it.

**Unknown means not stale**, for the same reason ``core.worktree_reaping``
refuses on unknown: a report that names a live worktree sends someone to
delete work. A worktree whose age cannot be read, a daemon whose root cannot be
attributed and a pid file that cannot be read are all left off the report.

**A worktree with no history of its own is not evidence that it is finished.**
A branch cut a moment ago is an ancestor of the base branch, exactly like one
merged long ago, and a branch cut from an old commit has an old last-commit
time. So "merged" needs the worktree to be at least
``worktree_reaping.MINIMUM_AGE_SECONDS`` old, "idle" needs it to be at least as
old as the idle window, and a live process whose cwd is inside it vetoes both.
"""

from __future__ import annotations

import shlex
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import psutil

from claude_code_hooks_daemon.core.worktree_reaping import (
    MINIMUM_AGE_SECONDS,
    ProcessCwdsFn,
    RunGit,
    WorktreeAgeFn,
    default_process_cwds,
    default_worktree_age,
)
from claude_code_hooks_daemon.daemon.paths import (
    get_untracked_dir,
    is_pid_alive,
    parse_pid_text,
    read_pid_file_text,
)
from claude_code_hooks_daemon.daemon.process_verification import (
    _extract_project_root,
    find_all_daemon_processes,
)
from claude_code_hooks_daemon.utils.git_repo import branch_ref, run_git
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to

DEFAULT_MAX_IDLE_DAYS: Final[int] = 7

_SECONDS_PER_DAY: Final[float] = 86400.0

_WORKTREE_PREFIX: Final[str] = "worktree "
_BRANCH_PREFIX: Final[str] = "branch refs/heads/"
_LOCKED_MARKER: Final[str] = "locked"
_PRUNABLE_MARKER: Final[str] = "prunable"

#: Every daemon pid file in an untracked dir: ``daemon.pid`` or the per-host
#: ``daemon-<host>.pid`` (``daemon.paths.get_pid_path``).
_PID_FILE_GLOB: Final[str] = "daemon*.pid"

#: ``stop`` removes a stale pid file under the daemon's start lock, which is the
#: only place that removal is allowed (``daemon.paths.read_pid_file``).
_STOP_COMMAND: Final[str] = "bin/hooks-daemon --project-root {root} stop"


@dataclass(frozen=True)
class StaleWorktree:
    """A registered worktree that looks finished, and how to clear it.

    Attributes:
        path: Where git says the worktree is.
        branch: The bare branch it has checked out, or None when detached.
        reasons: Why it is reported, each one a short clause.
        commands: The commands that clear it, in the order to run them. Offered,
            never run.
    """

    path: Path
    branch: str | None
    reasons: tuple[str, ...]
    commands: tuple[str, ...]


@dataclass(frozen=True)
class StaleDaemon:
    """A pid file or process belonging to a daemon with no live owner.

    Attributes:
        subject: What is stale: a pid file path, or ``daemon pid <n>``.
        reason: Why it is reported.
        commands: The commands that clear it. Offered, never run.
    """

    subject: str
    reason: str
    commands: tuple[str, ...]


@dataclass(frozen=True)
class DaemonProcess:
    """A running daemon server and the project root it serves.

    Attributes:
        pid: The daemon's pid.
        root: The project root the daemon was started for, or None when it
            cannot be attributed. Such a daemon is never reported.
    """

    pid: int
    root: str | None


DaemonProcessesFn = Callable[[], tuple[DaemonProcess, ...]]
PidAliveFn = Callable[[int], bool]
UntrackedDirFn = Callable[[Path], Path]


@dataclass(frozen=True)
class _Record:
    """One ``git worktree list --porcelain`` record, as far as this module reads it."""

    path: Path
    branch: str | None
    locked: bool
    prunable: bool


def _parse_records(listing: str) -> tuple[_Record, ...]:
    """Parse ``git worktree list --porcelain``; records are blank-line separated."""
    records: list[_Record] = []
    for block in listing.split("\n\n"):
        path: Path | None = None
        branch: str | None = None
        locked = False
        prunable = False
        for line in block.splitlines():
            if line.startswith(_WORKTREE_PREFIX):
                path = Path(line[len(_WORKTREE_PREFIX) :].strip())
            elif line.startswith(_BRANCH_PREFIX):
                branch = line[len(_BRANCH_PREFIX) :].strip()
            elif line.split(" ", 1)[0] == _LOCKED_MARKER:
                locked = True
            elif line.split(" ", 1)[0] == _PRUNABLE_MARKER:
                prunable = True
        if path is not None:
            records.append(_Record(path=path, branch=branch, locked=locked, prunable=prunable))
    return tuple(records)


def _list_records(repo_root: Path, run_fn: RunGit) -> tuple[_Record, ...]:
    """Every registered worktree, the main checkout first; empty when git cannot say."""
    listing = run_fn(repo_root, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return ()
    return _parse_records(listing.stdout)


def registered_checkouts(repo_root: Path, *, run_fn: RunGit = run_git) -> tuple[Path, ...]:
    """The main checkout and every linked worktree git knows, main first.

    Returns an empty tuple when the listing cannot be read: with no listing there
    is nothing to examine, which is the safe answer rather than a guess.
    """
    return tuple(record.path.resolve() for record in _list_records(repo_root, run_fn))


def _is_merged(repo_root: Path, branch: str, base_branch: str, run_fn: RunGit) -> bool:
    """Whether ``branch`` is an ancestor of the base. False also covers "git could not say"."""
    result = run_fn(
        repo_root, "merge-base", "--is-ancestor", branch_ref(branch), branch_ref(base_branch)
    )
    return result.returncode == 0


def _last_commit_time(repo_root: Path, branch: str, run_fn: RunGit) -> float | None:
    """Committer time of the branch tip, or None when git could not supply one."""
    result = run_fn(repo_root, "log", "-1", "--format=%ct", branch_ref(branch))
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _worktree_reasons(
    record: _Record,
    *,
    repo_root: Path,
    base_branch: str,
    max_idle_days: int,
    now: float,
    run_fn: RunGit,
    process_cwds: Mapping[int, Path],
    age_fn: WorktreeAgeFn,
) -> tuple[tuple[str, ...], bool]:
    """Why one worktree is stale, and whether its branch is merged.

    Returns no reasons for a worktree this module cannot vouch for as finished.
    """
    if not record.path.is_dir() or record.prunable:
        reasons = ["its directory is missing (git worktree prune clears the registration)"]
        merged = record.branch is not None and _is_merged(
            repo_root, record.branch, base_branch, run_fn
        )
        if merged:
            reasons.append(f"branch fully merged into {base_branch}")
        return tuple(reasons), merged

    resolved = record.path.resolve()
    if any(path_is_relative_to(cwd, resolved) for cwd in process_cwds.values()):
        return (), False

    age = age_fn(record.path)
    if age is None or record.branch is None:
        return (), False

    reasons = []
    merged = False
    if age >= MINIMUM_AGE_SECONDS and _is_merged(repo_root, record.branch, base_branch, run_fn):
        merged = True
        reasons.append(f"branch fully merged into {base_branch}")

    last_commit = _last_commit_time(repo_root, record.branch, run_fn)
    if last_commit is not None and age >= max_idle_days * _SECONDS_PER_DAY:
        idle_days = int((now - last_commit) // _SECONDS_PER_DAY)
        if idle_days >= max_idle_days:
            reasons.append(f"no commit for {idle_days} days")
    return tuple(reasons), merged


def _cleanup_commands(record: _Record, *, merged: bool) -> tuple[str, ...]:
    """The commands a human may run to clear a stale worktree, in order."""
    if not record.path.is_dir() or record.prunable:
        commands = ["git worktree prune"]
    else:
        commands = [f"git worktree remove {shlex.quote(str(record.path.resolve()))}"]
    # `git branch -d` refuses a branch that is not fully merged, so it is only
    # offered for one that is.
    if merged and record.branch is not None:
        commands.append(f"git branch -d {shlex.quote(record.branch)}")
    return tuple(commands)


def find_stale_worktrees(
    repo_root: Path,
    base_branch: str,
    *,
    max_idle_days: int = DEFAULT_MAX_IDLE_DAYS,
    now: float | None = None,
    run_fn: RunGit = run_git,
    process_cwds_fn: ProcessCwdsFn = default_process_cwds,
    age_fn: WorktreeAgeFn = default_worktree_age,
) -> tuple[StaleWorktree, ...]:
    """Registered linked worktrees that look finished. Read-only.

    A worktree is reported when its branch is fully merged into ``base_branch``,
    when its directory is missing (prunable), or when its branch has had no
    commit for ``max_idle_days``. The main checkout, locked worktrees (a
    deliberate hold), detached worktrees and any worktree with a live process
    inside it are never reported on merge or idleness grounds.

    Returns an empty tuple when git cannot list worktrees.
    """
    records = _list_records(repo_root, run_fn)[1:]
    if not records:
        return ()

    # One /proc scan serves every worktree in this run.
    process_cwds = dict(process_cwds_fn())
    current = time.time() if now is None else now
    found: list[StaleWorktree] = []
    for record in records:
        if record.locked or record.branch == base_branch:
            continue
        reasons, merged = _worktree_reasons(
            record,
            repo_root=repo_root,
            base_branch=base_branch,
            max_idle_days=max_idle_days,
            now=current,
            run_fn=run_fn,
            process_cwds=process_cwds,
            age_fn=age_fn,
        )
        if reasons:
            found.append(
                StaleWorktree(
                    path=record.path.resolve(),
                    branch=record.branch,
                    reasons=reasons,
                    commands=_cleanup_commands(record, merged=merged),
                )
            )
    return tuple(found)


def default_daemon_processes() -> tuple[DaemonProcess, ...]:
    """Every running daemon server on this host, with the root it serves.

    The calling process is excluded by ``find_all_daemon_processes``, so the
    daemon that hosts the advisory never reports itself.
    """
    processes: list[DaemonProcess] = []
    for pid in find_all_daemon_processes():
        try:
            root = _extract_project_root(psutil.Process(pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        processes.append(DaemonProcess(pid=pid, root=root))
    return tuple(processes)


def _stale_pid_files(root: Path, untracked: Path, pid_alive_fn: PidAliveFn) -> list[StaleDaemon]:
    """Pid files in ``untracked`` that name no running process."""
    found: list[StaleDaemon] = []
    for pid_file in sorted(untracked.glob(_PID_FILE_GLOB)):
        content = read_pid_file_text(pid_file)
        if content.text is None:
            # Absent or unreadable: neither is proof the file names no process.
            continue
        pid = parse_pid_text(content.text)
        if pid is None:
            reason = "its pid file is corrupt"
        elif not pid_alive_fn(pid):
            reason = f"pid {pid} is not running"
        else:
            continue
        found.append(
            StaleDaemon(
                subject=str(pid_file),
                reason=reason,
                commands=(_STOP_COMMAND.format(root=shlex.quote(str(root))),),
            )
        )
    return found


def find_stale_daemons(
    checkout_roots: Iterable[Path],
    *,
    processes_fn: DaemonProcessesFn = default_daemon_processes,
    pid_alive_fn: PidAliveFn = is_pid_alive,
    untracked_dir_fn: UntrackedDirFn = get_untracked_dir,
) -> tuple[StaleDaemon, ...]:
    """Daemon pid files with no live process, and daemons whose root is gone. Read-only.

    Args:
        checkout_roots: The checkouts whose pid files are read: each root's own
            untracked directory, where its daemon records itself.
        processes_fn: Lists running daemon servers. Injectable so a test uses a
            fake process table.
        pid_alive_fn: Liveness probe for a pid.
        untracked_dir_fn: Maps a checkout root to its daemon runtime directory.
    """
    found: list[StaleDaemon] = []
    for root in checkout_roots:
        untracked = untracked_dir_fn(root)
        if untracked.is_dir():
            found.extend(_stale_pid_files(root, untracked, pid_alive_fn))

    for process in processes_fn():
        if process.root is None or Path(process.root).is_dir():
            continue
        found.append(
            StaleDaemon(
                subject=f"daemon pid {process.pid}",
                reason=f"its project root {process.root} no longer exists",
                commands=(f"kill {process.pid}",),
            )
        )
    return tuple(found)


def render_stale_report(
    worktrees: Iterable[StaleWorktree], daemons: Iterable[StaleDaemon]
) -> str | None:
    """The report text, or None when nothing is stale (quiet by default)."""
    stale_worktrees = tuple(worktrees)
    stale_daemons = tuple(daemons)
    if not stale_worktrees and not stale_daemons:
        return None

    lines = [
        "STALE CHECKOUTS (report only; this advisory does not run any of these - "
        "inspect, then choose):"
    ]
    if stale_worktrees:
        lines.append("Stale worktrees:")
        for worktree in stale_worktrees:
            branch = f" [{worktree.branch}]" if worktree.branch else ""
            lines.append(f"  - {worktree.path}{branch}: {'; '.join(worktree.reasons)}")
            lines.extend(f"      {command}" for command in worktree.commands)
    if stale_daemons:
        lines.append("Stale daemons:")
        for daemon in stale_daemons:
            lines.append(f"  - {daemon.subject}: {daemon.reason}")
            lines.extend(f"      {command}" for command in daemon.commands)
    return "\n".join(lines)


def collect_stale_report(
    repo_root: Path, base_branch: str, max_idle_days: int = DEFAULT_MAX_IDLE_DAYS
) -> str | None:
    """Detect stale worktrees and daemons for ``repo_root`` and render the report."""
    worktrees = find_stale_worktrees(repo_root, base_branch, max_idle_days=max_idle_days)
    daemons = find_stale_daemons(registered_checkouts(repo_root))
    return render_stale_report(worktrees, daemons)
