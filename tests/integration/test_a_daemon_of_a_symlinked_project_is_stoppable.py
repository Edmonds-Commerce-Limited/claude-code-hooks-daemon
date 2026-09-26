"""Plan 00466 lifecycle round 9b: a symlinked project's daemon can be stopped.

A daemon's ``--project-root`` text is never resolved (review 9, DR-1). A
daemon ``init.sh`` started through a symlinked project path named the root
as ``pwd`` spelt it, link and all, while ``bin/hooks-daemon`` runs ``cd -P``
and names it resolved, so its ``stop`` refused that daemon. That broke
``restart`` for a symlinked project, and the upgrade's hand-off, which must
stop the old daemon.

Every launcher now names the resolved root, and ``bin/hooks-daemon`` and
the upgrade's daemon control also hand over the caller's logical root, the
spelling a daemon an older version started may carry. Real daemons, real
``init.sh`` starts and the real wrapper, against a project reached through
a link.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psutil
import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.paths import read_pid_file
from claude_code_hooks_daemon.daemon.process_verification import find_all_daemon_processes
from claude_code_hooks_daemon.install import bin_wrapper
from claude_code_hooks_daemon.utils.safe_signal import stop_verified_daemon
from tests.integration.test_init_sh_pretooluse_fail_closed import BASH, INIT_SH, _script_env

REPO_ROOT = Path(__file__).resolve().parents[2]
DAEMON_CONTROL_SH = REPO_ROOT / "scripts" / "install" / "daemon_control.sh"
_CLI_MODULE = "claude_code_hooks_daemon.daemon.cli"

#: How often the test looks again while it waits on a daemon.
_POLL_SECONDS = 0.1

_CONFIG = (
    "version: '1.0'\n"
    "daemon:\n"
    "  idle_timeout_seconds: 600\n"
    "  log_level: INFO\n"
    "  self_install_mode: true\n"
    "handlers:\n"
    "  pre_tool_use: {}\n"
)


@dataclass(frozen=True)
class Tree:
    """A project and its paths: ``real`` resolved, ``linked`` through a link."""

    base: Path
    real: Path
    linked: Path
    env: dict[str, str]

    @property
    def pid_path(self) -> Path:
        return self.base / "d.pid"

    def wrapper(self, through: str) -> Path:
        """The project's ``bin/hooks-daemon``, spelt through the link or not."""
        root = self.linked if through == "link" else self.real
        return root / ".claude" / "hooks-daemon" / "bin" / "hooks-daemon"


def _make_project(path: Path) -> None:
    """A client project whose ``bin/hooks-daemon`` runs this interpreter."""
    daemon_dir = path / ".claude" / "hooks-daemon"
    (daemon_dir / "untracked").mkdir(parents=True)
    shutil.copy(INIT_SH, path / ".claude" / "init.sh")
    (path / ".claude" / "hooks-daemon.yaml").write_text(_CONFIG)
    (path / ".claude" / "hooks-daemon.env").write_text(
        'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/.claude/hooks-daemon"\n'
    )
    for git in (["init", "-q"], ["remote", "add", "origin", "https://github.com/test/repo.git"]):
        subprocess.run(["git", "-C", str(path), *git], check=True, capture_output=True)
    bin_wrapper.deploy_bin_wrapper(daemon_dir)
    resolver = daemon_dir / "scripts" / "lib" / "resolve_venv.sh"
    resolver.parent.mkdir(parents=True)
    resolver.write_text(f"resolve_venv_python() {{ printf '%s\\n' '{sys.executable}'; }}\n")


def _stop_every_daemon(*roots: Path) -> None:
    for root in roots:
        for pid in find_all_daemon_processes(project_root=root):
            stop_verified_daemon(pid, project_root=root, grace_seconds=Timeout.PROCESS_DEATH_WAIT)


@pytest.fixture
def tree() -> Iterator[Tree]:
    """A project at ``r/p`` reached as ``l/p``, ``l`` a link to ``r``, in a
    directory short enough for AF_UNIX paths. Every daemon naming either
    spelling is stopped through the verified path afterwards."""
    base = Path(tempfile.mkdtemp(prefix="hd-link-"))
    real = base / "r" / "p"
    _make_project(real)
    (base / "l").symlink_to(base / "r")
    env = _script_env(
        base / "d.sock",
        extra_env={
            "CLAUDE_HOOKS_PID_PATH": str(base / "d.pid"),
            "CLAUDE_HOOKS_SOCKET_TIMEOUT": str(Timeout.SOCKET_CONNECT),
        },
    )
    try:
        yield Tree(base=base, real=real, linked=base / "l" / "p", env=env)
    finally:
        _stop_every_daemon(real, base / "l" / "p")
        shutil.rmtree(base)


def _cmdline(pid: int) -> list[str]:
    return psutil.Process(pid).cmdline()


def _root_named(pid: int) -> str:
    cmdline = _cmdline(pid)
    return cmdline[cmdline.index("--project-root") + 1]


def _gone(pid: int) -> bool:
    """True once ``pid`` has exited (a zombie awaiting its reaper counts)."""
    end = time.monotonic() + Timeout.PROCESS_DEATH_WAIT
    while time.monotonic() < end:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(_POLL_SECONDS)
    return False


def _running_daemon(tree: Tree) -> int:
    pid = read_pid_file(str(tree.pid_path))
    assert pid is not None, "no daemon is running"
    return pid


def _start_with_init_sh(tree: Tree) -> int:
    """Start the daemon as a hook does, sourcing ``init.sh`` through the link."""
    script = (
        f"source {tree.linked}/.claude/init.sh\nPYTHON_CMD={sys.executable}\n"
        "validate_venv() { return 0; }\n"
        "_is_ci_environment() { return 1; }\n_is_ci_enforced() { return 1; }\n"
        "ensure_daemon\n"
    )
    result = subprocess.run(
        [BASH, "-c", script],
        cwd=tree.linked,
        env=tree.env,
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return _running_daemon(tree)


def _start_naming_the_link(tree: Tree) -> int:
    """Start the daemon as an older ``init.sh`` did, naming the root through
    the link."""
    result = subprocess.run(
        [sys.executable, "-m", _CLI_MODULE, "--project-root", str(tree.linked), "start"],
        cwd=tree.base,
        env=tree.env,
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    pid = _running_daemon(tree)
    assert _root_named(pid) == str(tree.linked)
    return pid


def _wrapper(tree: Tree, through: str, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(tree.wrapper(through)), command],
        cwd=tree.base,
        env=tree.env,
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )


def test_init_sh_names_the_resolved_root(tree: Tree) -> None:
    """A daemon ``init.sh`` starts names the root its callers resolve to."""
    pid = _start_with_init_sh(tree)

    assert _root_named(pid) == str(tree.real)


@pytest.mark.parametrize("through", ["link", "real"])
def test_a_daemon_init_sh_started_through_a_link_is_stopped(tree: Tree, through: str) -> None:
    pid = _start_with_init_sh(tree)

    result = _wrapper(tree, through, "stop")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Daemon stopped" in result.stdout
    assert _gone(pid)


@pytest.mark.parametrize("through", ["link", "real"])
def test_a_daemon_init_sh_started_through_a_link_is_restarted(tree: Tree, through: str) -> None:
    pid = _start_with_init_sh(tree)

    result = _wrapper(tree, through, "restart")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _gone(pid)
    successor = _running_daemon(tree)
    assert successor != pid
    assert _root_named(successor) == str(tree.real)


def test_a_daemon_naming_the_link_is_stopped_through_the_link(tree: Tree) -> None:
    """The mixed-version case: an older version started it naming the link."""
    pid = _start_naming_the_link(tree)

    result = _wrapper(tree, "link", "stop")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _gone(pid)


def test_a_daemon_naming_a_link_since_re_pointed_is_refused(tree: Tree) -> None:
    """The daemon's text is never resolved: once the link names another
    tree, that tree's wrapper does not prove it, even with the same PID
    file."""
    pid = _start_naming_the_link(tree)
    other = tree.base / "o" / "p"
    _make_project(other)
    link = tree.base / "l"
    link.unlink()
    link.symlink_to(tree.base / "o")

    result = subprocess.run(
        [str(other / ".claude" / "hooks-daemon" / "bin" / "hooks-daemon"), "stop"],
        cwd=tree.base,
        env=tree.env,
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "is a daemon for project root" in result.stderr
    assert psutil.Process(pid).is_running()


def test_another_projects_wrapper_refuses_the_daemon(tree: Tree) -> None:
    pid = _start_with_init_sh(tree)
    other = tree.base / "o" / "p"
    _make_project(other)

    result = subprocess.run(
        [str(other / ".claude" / "hooks-daemon" / "bin" / "hooks-daemon"), "stop"],
        cwd=tree.base,
        env=tree.env,
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "is a daemon for project root" in result.stderr
    assert psutil.Process(pid).is_running()


def _daemon_control(tree: Tree, function: str) -> subprocess.CompletedProcess[str]:
    """Run a ``daemon_control.sh`` function as the upgrade does: standing
    at the project root it was given, here the path through the link."""
    script = f'set -euo pipefail\nsource "{DAEMON_CONTROL_SH}"\n{function} "{sys.executable}"\n'
    env = dict(tree.env)
    env["PWD"] = str(tree.linked)
    return subprocess.run(
        [BASH, "-c", f'cd "{tree.linked}"\n{script}'],
        cwd=tree.base,
        env=env,
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )


@pytest.mark.parametrize("started", ["init_sh", "naming_the_link"])
def test_the_upgrades_stop_stops_the_old_daemon(tree: Tree, started: str) -> None:
    pid = _start_with_init_sh(tree) if started == "init_sh" else _start_naming_the_link(tree)

    result = _daemon_control(tree, "stop_daemon_safe")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _gone(pid), result.stdout + result.stderr


def test_the_upgrades_restart_replaces_a_daemon_naming_the_link(tree: Tree) -> None:
    pid = _start_naming_the_link(tree)

    result = _daemon_control(tree, "restart_daemon_verified")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _gone(pid)
    successor = _running_daemon(tree)
    assert successor != pid
    assert _root_named(successor) == str(tree.real)
