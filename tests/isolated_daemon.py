"""Helpers for tests that run a daemon of their own through the CLI."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final, NamedTuple

from claude_code_hooks_daemon.constants import Timeout

#: How long a test lets a ``hooks-daemon`` lifecycle command run before
#: calling it hung. ``start`` waits for the launch lock another start holds,
#: then for the daemon it launched while that makes progress, each for up to
#: ``Timeout.DAEMON_START_BUDGET_SEC``; ``stop`` waits up to
#: ``Timeout.DAEMON_SHUTDOWN`` for the daemon to exit; and on a loaded host
#: the interpreter alone can take seconds to start. A shorter subprocess
#: timeout cuts a slow command short: the test reports TimeoutExpired for a
#: command that would have succeeded, and a daemon it started, or failed to
#: stop, is left running. Every command bounds itself well inside this.
DAEMON_CLI_SUBPROCESS_BOUND: Final = 4 * Timeout.DAEMON_START_BUDGET_SEC

#: Hex digits of the path key: short enough for a socket path, long enough
#: that two live test directories never share one.
_KEY_LENGTH: Final = 16


class IsolatedDaemonPaths(NamedTuple):
    """Where a test's own daemon keeps its socket, PID file and log."""

    socket: Path
    pid: Path
    log: Path


def isolated_daemon_paths(tmp_path: Path, prefix: str) -> IsolatedDaemonPaths:
    """Paths for a test's own daemon, unique to ``tmp_path``.

    They sit directly under /tmp, since an AF_UNIX path is limited to 108
    bytes. They are keyed by the whole of ``tmp_path``: its last part, the
    test's name, is the same in every pytest session, and the test matrix
    runs its interpreters side by side while other checkouts on the host run
    the same tests. Keyed by that part alone, two sessions shared one
    daemon's files, and one session's ``stop`` met the other's daemon.
    """
    key = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:_KEY_LENGTH]
    base = f"/tmp/test-{prefix}-{key}"
    return IsolatedDaemonPaths(
        socket=Path(f"{base}.sock"), pid=Path(f"{base}.pid"), log=Path(f"{base}.log")
    )
