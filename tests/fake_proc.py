"""Fake ``/proc`` trees for the thread-grouping tests (Plan 00470 Task 6.4)."""

from __future__ import annotations

import shutil
from pathlib import Path

#: ``claude daemon run`` as a session's front end spawns it.
DAEMON_ARGV = [
    "claude",
    "daemon",
    "run",
    "--origin",
    "transient",
    "--spawned-by",
    '{"pid":580792,"x":1}',
]

#: The initial thread's worker once threads exist.
INITIAL_WORKER_ARGV = ["2.1.292", "--session-id", "abc", "--fork-session", "--resume", "abc"]

#: A thread opened later: a claimed pre-started spare.
SPARE_WORKER_ARGV = ["claude", "bg-spare", "--bg-spare", "/tmp/spare/x.claim.sock"]

PTY_HOST_ARGV = ["claude", "bg-pty-host", "--bg-pty-host", "/tmp/pty/x.sock"]


def add_proc(
    root: Path,
    pid: int,
    ppid: int,
    argv: list[str],
    *,
    start: int = 1000,
    comm: str = "claude",
) -> None:
    """Write one fake /proc/<pid> with a stat line and a cmdline."""
    proc = root / str(pid)
    proc.mkdir(parents=True)
    # Fields after the ')' are: state ppid pgrp session tty tpgid flags minflt cminflt
    # majflt cmajflt utime stime cutime cstime priority nice threads itrealvalue starttime ...
    rest = ["S", str(ppid)] + ["0"] * 17 + [str(start), "0", "0"]
    (proc / "stat").write_text(f"{pid} ({comm}) {' '.join(rest)}\n")
    (proc / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


def remove_proc(root: Path, pid: int) -> None:
    """The process exits."""
    shutil.rmtree(root / str(pid))


def add_thread(
    root: Path,
    daemon_pid: int,
    worker_pid: int,
    hook_pid: int,
    worker_argv: list[str],
    *,
    worker_start: int = 1000,
) -> None:
    """One thread: ``daemon run`` <- bg-pty-host <- worker <- hook."""
    pty_pid = worker_pid + 5000
    if not (root / str(pty_pid)).exists():
        add_proc(root, pty_pid, daemon_pid, PTY_HOST_ARGV)
    add_proc(root, worker_pid, pty_pid, worker_argv, start=worker_start)
    add_proc(root, hook_pid, worker_pid, ["relay"])
