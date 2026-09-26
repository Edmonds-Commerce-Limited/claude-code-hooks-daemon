"""A process whose command line is a project's daemon server (Plan 00466 round 5).

``init.sh``'s ``is_daemon_running`` counts a live pid as the daemon only when
it is proven (Sh-D): its command line has the form ``start_daemon`` launches
a daemon of the project with, or the daemon's socket answers. A test that
needs "the daemon is running" without a real daemon names this process in
its PID file. It does nothing but wait on its stdin, and it ends when the
context closes that stdin: no signal is ever sent to it.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from claude_code_hooks_daemon.constants import Timeout

DAEMON_CLI_MODULE = "claude_code_hooks_daemon.daemon.cli"


@contextlib.contextmanager
def daemon_like_process(project_root: Path) -> Iterator[int]:
    """Yield the pid of a process launched as ``project_root``'s daemon is."""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdin.read()",
            "-m",
            DAEMON_CLI_MODULE,
            "--project-root",
            str(project_root),
            "start",
        ],
        stdin=subprocess.PIPE,
    )
    try:
        yield process.pid
    finally:
        assert process.stdin is not None
        process.stdin.close()
        process.wait(timeout=Timeout.REQUEST_LONG)
