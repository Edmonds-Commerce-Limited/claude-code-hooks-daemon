"""Plan 00291 canary finding — init.sh must follow the PID file into the runtime dir.

When a project's default socket path exceeds the AF_UNIX limit the daemon
(``paths.get_socket_path`` / ``paths.get_pid_path``) puts BOTH its socket and
its PID file in a short runtime directory under one stem
(``hooks-daemon-<hash>.sock`` / ``.pid``) and leaves a ``.socket-path``
discovery file behind. ``init.sh`` read that discovery file for the socket
but kept ``PID_PATH`` at the long default, so ``is_daemon_running`` said
"no", ``daemon.cli start`` saw a live socket with no PID of ours and refused
to steal it, and every hook forwarder reported ``daemon_startup_failed``
while ``status`` showed the daemon RUNNING. The php-qa-ci canary, cloned
under a long enough path, hit exactly this on its first hook.

Behavioural: sources the real ``init.sh`` in a bare fixture project whose
discovery file points at a genuinely bound socket, and reads the exported
paths back.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"
BASH = shutil.which("bash") or "/bin/bash"
_HOSTNAME = "discovery-fixture"


@pytest.fixture
def bound_socket() -> Iterator[Path]:
    """A real, bound AF_UNIX socket at a path short enough to bind."""
    short_dir = Path(tempfile.mkdtemp(prefix="hd-", dir="/tmp"))
    sock_path = short_dir / "hooks-daemon-cafef00d.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(sock_path))
    sock.listen(1)
    try:
        yield sock_path
    finally:
        sock.close()
        shutil.rmtree(short_dir, ignore_errors=True)


_AF_UNIX_LIMIT = 104  # daemon/paths.py:_UNIX_SOCKET_PATH_LIMIT
_PID_TAIL = f"/.claude/hooks-daemon/untracked/daemon-{_HOSTNAME}.pid"


@pytest.fixture
def short_base() -> Iterator[Path]:
    """A short directory, so a project path can be padded to an exact length under it."""
    base = Path(tempfile.mkdtemp(prefix="pp-", dir="/tmp")).resolve()
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _project_with_pid_path_length(short_base: Path, pid_path_length: int) -> Path:
    """A project whose natural PID path is exactly ``pid_path_length`` characters."""
    base = short_base / "p"
    pad = pid_path_length - len(str(base)) - len(_PID_TAIL)
    assert pad >= 0, "short base too long for the requested PID path length"
    root = Path(f"{base}{'x' * pad}")
    return _make_project(root)


@pytest.fixture
def project(short_base: Path) -> Path:
    """A project whose PID path overflows the AF_UNIX limit, as a long checkout path does."""
    return _project_with_pid_path_length(short_base, _AF_UNIX_LIMIT + 1)


def _make_project(root: Path) -> Path:
    (root / ".claude" / "hooks-daemon" / "untracked").mkdir(parents=True)
    shutil.copy(INIT_SH, root / ".claude" / "init.sh")
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / ".claude" / "hooks-daemon.env").write_text(
        'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/.claude/hooks-daemon"\n'
    )
    return root


def _resolved_paths(project: Path, extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_HOOKS_", "HOOKS_DAEMON_"))
    }
    env["HOSTNAME"] = _HOSTNAME
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [
            BASH,
            "-c",
            'source .claude/init.sh; printf "SOCKET=%s\\nPID=%s\\n" "$SOCKET_PATH" "$PID_PATH"',
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return lines


def test_pid_path_follows_the_discovered_socket(project: Path, bound_socket: Path) -> None:
    untracked = project / ".claude" / "hooks-daemon" / "untracked"
    (untracked / f"daemon-{_HOSTNAME}.socket-path").write_text(f"{bound_socket}\n")

    paths = _resolved_paths(project)

    assert paths["SOCKET"] == str(bound_socket)
    assert paths["PID"] == str(bound_socket.with_suffix(".pid")), (
        "init.sh followed the discovery file for the socket but left PID_PATH at the "
        "long default, so the daemon that wrote the discovery file is invisible to "
        "is_daemon_running and every forwarder refuses to talk to it"
    )


def test_pid_path_stays_natural_when_only_the_socket_overflows(
    short_base: Path, bound_socket: Path
) -> None:
    """A PID path of exactly the limit fits while its one-character-longer socket does not.

    The daemon then binds its socket in the runtime dir but leaves the PID file
    in the untracked dir (paths.pid_path_for decides on the PID path's own
    length). init.sh must look where the daemon wrote it: a CI checkout sat at
    exactly this boundary, every forwarder judged the live daemon dead, and the
    hooks silently passed everything through.
    """
    root = _project_with_pid_path_length(short_base, _AF_UNIX_LIMIT)
    untracked = root / ".claude" / "hooks-daemon" / "untracked"
    (untracked / f"daemon-{_HOSTNAME}.socket-path").write_text(f"{bound_socket}\n")

    paths = _resolved_paths(root)

    assert paths["SOCKET"] == str(bound_socket)
    assert paths["PID"] == str(untracked / f"daemon-{_HOSTNAME}.pid")


def test_pid_path_stays_default_without_a_discovery_file(project: Path) -> None:
    paths = _resolved_paths(project)
    untracked = project / ".claude" / "hooks-daemon" / "untracked"
    assert paths["PID"] == str(untracked / f"daemon-{_HOSTNAME}.pid")


def test_explicit_pid_override_wins_over_discovery(project: Path, bound_socket: Path) -> None:
    untracked = project / ".claude" / "hooks-daemon" / "untracked"
    (untracked / f"daemon-{_HOSTNAME}.socket-path").write_text(f"{bound_socket}\n")

    paths = _resolved_paths(project, {"CLAUDE_HOOKS_PID_PATH": "/tmp/explicit.pid"})

    assert paths["PID"] == "/tmp/explicit.pid"
