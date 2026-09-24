"""A client project whose daemon clone has no venv for this path (Plan 00456, #53).

Shared by the tests that drive the self-healing venv build through its real
entry points: init.sh's hook path, ``bin/hooks-daemon repair``, and the
hooks-daemon skill's ``install.sh``.

The project's ``.claude/init.sh`` is a copy of this repository's. Its clone
under ``.claude/hooks-daemon`` carries copies of exactly the scripts those
paths run: the bootstrap driver, ``scripts/install`` and ``scripts/lib``,
``paths.py`` and ``bin/hooks-daemon``. It also holds its own
``pyproject.toml``, ``uv.lock`` and ``version.py``. A stub ``uv`` builds the
venv. Its ``bin/python`` runs the test interpreter, so the package imports,
except for the daemon CLI's ``start``. That call is recorded, a live PID is
written and a socket is bound where init.sh looks, so init.sh's real readiness
check passes without a real daemon.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
BASH: Final[str] = shutil.which("bash") or "/bin/bash"
TIMEOUT_SECONDS: Final[int] = 60
BUILD_WAIT_SECONDS: Final[float] = 30.0
CLONE_VERSION: Final[str] = "3.61.0"
OTHER_VIEW_VENV: Final[str] = "venv-home_dev_project_claude_hooks-daemon-py311-0badc0de"

#: init.sh's own per-source runtime file (the hourly exec-bit throttle). It
#: predates Plan 00456 and is written on every source, so "changes nothing" is
#: judged without it.
INIT_SH_THROTTLE: Final[str] = "untracked/.exec-bit-checked"

#: What a clone contributes to the paths under test, copied verbatim.
CLONE_FILES: Final[tuple[str, ...]] = (
    "scripts/venv_bootstrap.sh",
    "scripts/install/venv.sh",
    "scripts/install/output.sh",
    "scripts/install/python_fingerprint.sh",
    "scripts/lib/resolve_venv.sh",
    "scripts/lib/python_discovery.sh",
    "src/claude_code_hooks_daemon/daemon/paths.py",
    "bin/hooks-daemon",
)

_TOOLS: Final[tuple[str, ...]] = (
    "bash",
    "sh",
    "env",
    "python3",
    "jq",
    "cat",
    "dirname",
    "basename",
    "mkdir",
    "rmdir",
    "rm",
    "mv",
    "cp",
    "touch",
    "chmod",
    "date",
    "sleep",
    "stat",
    "uname",
    "grep",
    "awk",
    "sed",
    "tr",
    "hostname",
    "flock",
    "setsid",
    "nohup",
    "sync",
    "mktemp",
    "head",
    "cut",
    "wc",
    "ls",
    "readlink",
    "kill",
    "find",
)

#: The forwarders' own shape, with CI detection pinned off (CI runners export
#: CI=true, which routes ensure_daemon to passthrough before any diagnosis).
_HOOK: Final[str] = textwrap.dedent("""\
    _is_ci_environment() { return 1; }
    _is_ci_enforced() { return 1; }
    if ensure_daemon; then
        echo "ENSURE_DAEMON_OK"
    else
        emit_hook_error "__EVENT__" "daemon_startup_failed" "Failed to start hooks daemon"
    fi
    """)


class Sandbox:
    """A client project whose clone has no venv for this path."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.project = tmp_path / "project"
        self.clone = self.project / ".claude" / "hooks-daemon"
        self.uv_log = tmp_path / "uv-calls.log"
        self.start_log = tmp_path / "daemon-starts.log"
        # AF_UNIX paths are capped near 108 bytes and pytest's tmp paths are
        # long, so the socket and PID live in a short directory of their own.
        self.runtime = Path(tempfile.mkdtemp(prefix="hd456-", dir="/tmp"))
        self.socket = self.runtime / "d.sock"
        self.pid = self.runtime / "d.pid"
        self._build()

    def _build(self) -> None:
        claude = self.project / ".claude"
        claude.mkdir(parents=True)
        shutil.copy2(REPO_ROOT / "init.sh", claude / "init.sh")
        for rel in CLONE_FILES:
            dest = self.clone / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / rel, dest)
        (self.clone / "src" / "claude_code_hooks_daemon" / "version.py").write_text(
            f'__version__ = "{CLONE_VERSION}"\n'
        )
        (self.clone / "pyproject.toml").write_text(
            f'[project]\nname = "fake"\nversion = "{CLONE_VERSION}"\n'
            'requires-python = ">=3.11"\n'
        )
        (self.clone / "uv.lock").write_text("# lock v1\n")
        (self.clone / "untracked").mkdir()

        tools = self.root / "tools"
        tools.mkdir()
        for tool in _TOOLS:
            real = shutil.which(tool)
            if real is not None:
                (tools / tool).symlink_to(real)
        (self.root / "home").mkdir()

    def stub_uv(self, *, sleep: float = 0.0, fail: bool = False) -> None:
        """Put a `uv` on PATH that builds (or fails to build) a usable venv."""
        stub_dir = self.root / "uv-stub"
        stub_dir.mkdir(exist_ok=True)
        venv_python = textwrap.dedent(f"""\
            #!/bin/bash
            if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "claude_code_hooks_daemon.daemon.cli" ] \\
                    && [ "${{!#}}" = "start" ]; then
                echo "$0" >> "{self.start_log}"
                sleep 60 < /dev/null > /dev/null 2>&1 &
                echo $! > "$CLAUDE_HOOKS_PID_PATH"
                exec "{sys.executable}" -c \\
                    'import socket, sys; socket.socket(socket.AF_UNIX).bind(sys.argv[1])' \\
                    "$CLAUDE_HOOKS_SOCKET_PATH"
            fi
            exec "{sys.executable}" "$@"
            """)
        template = self.root / "venv-python.template"
        template.write_text(venv_python)
        (stub_dir / "uv").write_text(textwrap.dedent(f"""\
            #!/bin/bash
            echo "uv $* target=${{UV_PROJECT_ENVIRONMENT:-UNSET}}" >> "{self.uv_log}"
            sleep {sleep}
            if [ "{int(fail)}" = "1" ]; then
                echo "error: simulated failure (network unreachable)" >&2
                exit 2
            fi
            mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
            cp "{template}" "$UV_PROJECT_ENVIRONMENT/bin/python"
            chmod +x "$UV_PROJECT_ENVIRONMENT/bin/python"
            """))
        (stub_dir / "uv").chmod(0o755)

    def other_view_venv(self) -> Path:
        """Another environment's venv: a different slug, a dangling interpreter."""
        venv = self.clone / "untracked" / OTHER_VIEW_VENV
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").symlink_to("/nonexistent/host-only/python3.11")
        (venv / "pyvenv.cfg").write_text("home = /nonexistent/host-only\n")
        (venv / ".daemon-metadata.json").write_text('{"python_path": "x", "lock_hash": "y"}\n')
        return venv

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        path = [str(self.root / "tools")]
        if (self.root / "uv-stub").is_dir():
            path.insert(0, str(self.root / "uv-stub"))
        env = {
            "PATH": ":".join(path),
            # venv.sh prepends $HOME/.local/bin, uv's default home: a tmp HOME
            # keeps this machine's real uv out of the picture.
            "HOME": str(self.root / "home"),
            # Deterministic interpreter: the gate, the build and the resolver.
            "HOOKS_DAEMON_PYTHON": sys.executable,
            "CLAUDE_HOOKS_SOCKET_PATH": str(self.socket),
            "CLAUDE_HOOKS_PID_PATH": str(self.pid),
            "NO_COLOR": "1",
        }
        if extra:
            env.update(extra)
        return env

    def hook_argv(self, event: str = "PreToolUse") -> list[str]:
        init_sh = self.project / ".claude" / "init.sh"
        return [BASH, "-c", f'source "{init_sh}"\n' + _HOOK.replace("__EVENT__", event)]

    def hook(
        self, event: str = "PreToolUse", extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run one hook the way a forwarder does."""
        return self.run(self.hook_argv(event), extra_env=extra_env)

    def wrapper(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the clone's own ``bin/hooks-daemon``."""
        return self.run([BASH, str(self.clone / "bin" / "hooks-daemon"), *args])

    def run(
        self,
        argv: list[str],
        *,
        extra_env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 - fixed argv built from tmp paths, no shell
            argv,
            capture_output=True,
            text=True,
            env=self.env(extra_env),
            cwd=cwd or self.project,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )

    def uv_calls(self) -> list[str]:
        return self.uv_log.read_text().splitlines() if self.uv_log.exists() else []

    def failed_markers(self) -> list[Path]:
        return sorted((self.clone / "untracked").glob(".venv-bootstrap-*.failed"))

    def resolves(self) -> bool:
        """Does a venv now resolve for this clone, by the canonical resolver?"""
        result = self.run(
            [
                BASH,
                str(self.clone / "scripts" / "lib" / "resolve_venv.sh"),
                "python",
                str(self.clone),
            ]
        )
        return result.returncode == 0 and result.stdout.strip() != ""

    def wait_for_build(self) -> None:
        """The background build holds the venv lock for exactly as long as it runs."""
        lock = self.clone / "untracked" / ".venv-bootstrap.lock"
        deadline = time.monotonic() + BUILD_WAIT_SECONDS
        while time.monotonic() < deadline:
            probe = subprocess.run(  # nosec B603 - fixed argv, no shell
                ["flock", "-n", str(lock), "true"], capture_output=True, check=False
            )
            if probe.returncode == 0:
                return
            time.sleep(0.2)
        raise AssertionError("the background build never released the venv lock")

    def cleanup(self) -> None:
        """Stop the stand-in daemon process, if a test started one."""
        if self.pid.exists():
            pid = int(self.pid.read_text().strip())
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                # Already gone: its 60s sleep ran out before teardown.
                print(f"stand-in daemon pid {pid} had already exited", file=sys.stderr)
        shutil.rmtree(self.runtime)


def snapshot(root: Path) -> dict[str, str]:
    """Every path under root, with its bytes or link target (init.sh's throttle excluded)."""
    state: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in sorted(dirnames + filenames):
            path = Path(dirpath) / name
            rel = str(path.relative_to(root))
            if rel == INIT_SH_THROTTLE:
                continue
            if path.is_symlink():
                state[rel] = f"link:{path.readlink()}"
            elif path.is_dir():
                state[rel] = "dir"
            else:
                state[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return state


def assert_never_suggests_install_or_force(text: str) -> None:
    """#53's invariant: this state's advice never names install or --force."""
    lowered = text.lower()
    assert "args=install" not in lowered
    assert "--force" not in lowered
    assert "force=true" not in lowered
