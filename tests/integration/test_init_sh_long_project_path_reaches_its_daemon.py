"""Plan 00628: a hook in a long project path starts a daemon it can reach.

A client seat whose project path was long had EVERY tool call denied.
``init.sh`` found no discovery file, started the daemon with its own default
socket path forced through ``CLAUDE_HOOKS_SOCKET_PATH`` (109 characters
against the 104-character limit), the bind failed with "AF_UNIX path too
long", and every hook reported ``daemon_startup_failed`` while ``status``,
which computes the shortened path itself, reported a daemon RUNNING.

Real ``init.sh``, real daemon, a project padded so its natural socket path
cannot be bound, and no discovery file beforehand: the SAME hook invocation
that starts the daemon must get it running and reachable, at the path the
management CLI also reports.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout
from tests.daemon_teardown import stop_daemons_of

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"
BASH = shutil.which("bash") or "/bin/bash"
_CLI_MODULE = "claude_code_hooks_daemon.daemon.cli"
_HOST = "client-seat-dev-vm01"  # 20 characters, as on the reporting seat
_NATURAL_SOCKET_LENGTH = 109  # what the reporting seat had; over every platform's limit
_SOCKET_TAIL = f"/.claude/hooks-daemon/untracked/daemon-{_HOST}.sock"
_CONFIG = (
    "version: '1.0'\n"
    "daemon:\n"
    "  idle_timeout_seconds: 600\n"
    "  log_level: INFO\n"
    "  self_install_mode: true\n"
    "handlers:\n"
    "  pre_tool_use: {}\n"
)


@pytest.fixture
def long_project() -> Iterator[tuple[Path, Path]]:
    """``(project, runtime_dir)``: a project whose natural socket path is 109 chars."""
    base = Path(tempfile.mkdtemp(prefix="hd-long-")).resolve()
    runtime_dir = base / "run"
    runtime_dir.mkdir(mode=0o700)
    runtime_dir.chmod(0o700)
    pad = _NATURAL_SOCKET_LENGTH - len(str(base / "p")) - len(_SOCKET_TAIL)
    assert pad > 0, "temporary directory too long to build the fixture"
    root = base / ("p" + "x" * pad)
    assert len(str(root) + _SOCKET_TAIL) == _NATURAL_SOCKET_LENGTH
    (root / ".claude" / "hooks-daemon" / "untracked").mkdir(parents=True)
    shutil.copy(INIT_SH, root / ".claude" / "init.sh")
    (root / ".claude" / "hooks-daemon.yaml").write_text(_CONFIG)
    (root / ".claude" / "hooks-daemon.env").write_text(
        'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/.claude/hooks-daemon"\n'
    )
    for git in (["init", "-q"], ["remote", "add", "origin", "https://github.com/test/repo.git"]):
        subprocess.run(["git", "-C", str(root), *git], check=True, capture_output=True)
    try:
        yield root, runtime_dir
    finally:
        stop_daemons_of(root, grace_seconds=Timeout.PROCESS_DEATH_WAIT)
        shutil.rmtree(base, ignore_errors=True)


def _env(runtime_dir: Path) -> dict[str, str]:
    """A hook's environment: no socket or PID override, nothing from this session."""
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_HOOKS_", "HOOKS_DAEMON_"))
    }
    for ci_var in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL", "TF_BUILD"):
        env.pop(ci_var, None)
    env["HOSTNAME"] = _HOST
    env["XDG_RUNTIME_DIR"] = str(runtime_dir)
    return env


def _connects(path: str) -> bool:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(Timeout.SOCKET_CONNECT)
        probe.connect(path)
    except OSError:
        return False
    finally:
        probe.close()
    return True


def test_one_hook_start_reaches_the_daemon(long_project: tuple[Path, Path]) -> None:
    root, runtime_dir = long_project
    discovery = root / ".claude" / "hooks-daemon" / "untracked" / f"daemon-{_HOST}.socket-path"
    assert not discovery.exists()

    script = (
        "source .claude/init.sh\n"
        f"PYTHON_CMD={sys.executable}\n"
        "validate_venv() { return 0; }\n"
        "_is_ci_environment() { return 1; }\n_is_ci_enforced() { return 1; }\n"
        "ensure_daemon || exit 7\n"
        'printf "SOCKET=%s\\n" "$SOCKET_PATH"\n'
    )
    hook = subprocess.run(
        [BASH, "-c", script],
        cwd=root,
        env=_env(runtime_dir),
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )
    assert hook.returncode == 0, hook.stdout + hook.stderr
    hook_socket = dict(
        line.split("=", 1) for line in hook.stdout.splitlines() if line.startswith("SOCKET=")
    )["SOCKET"]

    assert len(hook_socket) <= 104
    assert Path(hook_socket).parent == runtime_dir
    assert _connects(hook_socket), "the hook's socket must answer"

    status = subprocess.run(
        [sys.executable, "-m", _CLI_MODULE, "--project-root", str(root), "status"],
        cwd=root,
        env=_env(runtime_dir),
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )
    assert "Daemon: RUNNING" in status.stdout, status.stdout + status.stderr
    assert f"Socket: {hook_socket}" in status.stdout, "status and the hooks must name one socket"
