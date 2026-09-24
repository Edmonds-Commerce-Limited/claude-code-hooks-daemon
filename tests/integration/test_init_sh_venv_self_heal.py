"""A clone with no venv for this path heals itself from the hook path (Plan 00456, #53).

Plan 00454 gave the "clone present, venv missing for this project path" state
its own message. This module pins what init.sh now DOES in that state. It
calls the clone's ``scripts/venv_bootstrap.sh hook``, which checks the five
``can_inline_bootstrap`` preconditions with no venv and, when they hold,
starts ONE detached build under the venv build lock. The message says which of
these happened:

- a build started, or is already running (with its log);
- the last build failed (with its log and ``repair``), and is not retried;
- the build was refused, with each failed condition and its fix, and
  nothing changed;
- the opt-out is set.

It never recommends install or ``--force``. Once the build finishes, the next
hook starts the daemon from the new venv.

The tmp project is a client install. Its ``.claude/init.sh`` is a copy of this
repository's, and its clone carries copies of exactly the scripts the path
runs: the driver, ``scripts/install`` and ``scripts/lib``, ``paths.py`` and
``bin/hooks-daemon``. A stub ``uv`` builds the venv. Its ``bin/python`` runs
this test's interpreter (so the package imports), except for the daemon CLI's
``start``. That call is recorded, a live PID is written and a socket is bound
where init.sh looks, so init.sh's real readiness check passes without a real
daemon.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
BASH: Final[str] = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS: Final[int] = 60
_BUILD_WAIT_SECONDS: Final[float] = 30.0
_CLONE_VERSION: Final[str] = "3.61.0"
_OTHER_VIEW_VENV: Final[str] = "venv-home_dev_project_claude_hooks-daemon-py311-0badc0de"

#: init.sh's own per-source runtime file (the hourly exec-bit throttle). It
#: predates this plan and is written on every source, so "changes nothing"
#: is judged without it.
_INIT_SH_THROTTLE: Final[str] = "untracked/.exec-bit-checked"

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
)

#: The forwarders' own shape, with CI detection pinned off (CI runners export
#: CI=true, which routes ensure_daemon to passthrough before any diagnosis).
_HOOK = textwrap.dedent("""\
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
        for rel in (
            "scripts/venv_bootstrap.sh",
            "scripts/install/venv.sh",
            "scripts/install/output.sh",
            "scripts/install/python_fingerprint.sh",
            "scripts/lib/resolve_venv.sh",
            "scripts/lib/python_discovery.sh",
            "src/claude_code_hooks_daemon/daemon/paths.py",
            "bin/hooks-daemon",
        ):
            dest = self.clone / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / rel, dest)
        (self.clone / "src" / "claude_code_hooks_daemon" / "version.py").write_text(
            f'__version__ = "{_CLONE_VERSION}"\n'
        )
        (self.clone / "pyproject.toml").write_text(
            f'[project]\nname = "fake"\nversion = "{_CLONE_VERSION}"\n'
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
        venv = self.clone / "untracked" / _OTHER_VIEW_VENV
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
            "HOME": str(self.root / "home"),
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
        return subprocess.run(  # nosec B603 - fixed argv, no shell
            self.hook_argv(event),
            capture_output=True,
            text=True,
            env=self.env(extra_env),
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )

    def uv_calls(self) -> list[str]:
        return self.uv_log.read_text().splitlines() if self.uv_log.exists() else []

    def wait_for_build(self) -> None:
        lock = self.clone / "untracked" / ".venv-bootstrap.lock"
        deadline = time.monotonic() + _BUILD_WAIT_SECONDS
        while time.monotonic() < deadline:
            probe = subprocess.run(  # nosec B603 - fixed argv, no shell
                ["flock", "-n", str(lock), "true"], capture_output=True, check=False
            )
            if probe.returncode == 0:
                return
            time.sleep(0.2)
        raise AssertionError("the background build never released the venv lock")

    def cleanup(self) -> None:
        if self.pid.exists():
            try:
                os.kill(int(self.pid.read_text().strip()), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
        shutil.rmtree(self.runtime)


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    box = Sandbox(tmp_path)
    yield box
    box.cleanup()


def _context(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    return str(payload["hookSpecificOutput"]["additionalContext"])


def _snapshot(root: Path) -> dict[str, str]:
    state: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in sorted(dirnames + filenames):
            path = Path(dirpath) / name
            rel = str(path.relative_to(root))
            if rel == _INIT_SH_THROTTLE:
                continue
            if path.is_symlink():
                state[rel] = f"link:{path.readlink()}"
            elif path.is_dir():
                state[rel] = "dir"
            else:
                state[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return state


def _assert_never_suggests_install_or_force(context: str) -> None:
    lowered = context.lower()
    assert "args=install" not in lowered
    assert "--force" not in lowered
    assert "force=true" not in lowered


class TestTheHookHealsTheVenv:
    def test_the_first_hook_starts_a_build_and_says_so(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        started = time.monotonic()
        context = _context(sandbox.hook())
        elapsed = time.monotonic() - started

        assert "build" in context.lower() and "started" in context.lower(), context
        log_lines = [ln for ln in context.splitlines() if ".venv-bootstrap-" in ln]
        assert log_lines, f"the message must name the build's log:\n{context}"
        assert str(sandbox.clone / "untracked") in log_lines[0]
        _assert_never_suggests_install_or_force(context)
        assert elapsed < 20, f"the hook must return without waiting for the build ({elapsed:.1f}s)"
        sandbox.wait_for_build()
        assert len(sandbox.uv_calls()) == 1

    def test_concurrent_hooks_start_exactly_one_build(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv(sleep=3)
        procs = [
            subprocess.Popen(  # nosec B603 - fixed argv, no shell
                sandbox.hook_argv(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=sandbox.env(),
            )
            for _ in range(5)
        ]
        contexts: list[str] = []
        for proc in procs:
            stdout, stderr = proc.communicate(timeout=_TIMEOUT_SECONDS)
            assert proc.returncode == 0, stderr
            contexts.append(json.loads(stdout)["hookSpecificOutput"]["additionalContext"])

        sandbox.wait_for_build()
        assert len(sandbox.uv_calls()) == 1, sandbox.uv_calls()
        started = [c for c in contexts if "build has started" in c.lower()]
        assert len(started) == 1, contexts
        assert all("build" in c.lower() for c in contexts)

    def test_the_next_hook_after_the_build_starts_the_daemon(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        _context(sandbox.hook())
        sandbox.wait_for_build()

        result = sandbox.hook()

        assert "ENSURE_DAEMON_OK" in result.stdout, result.stdout + result.stderr
        starts = sandbox.start_log.read_text().splitlines()
        assert len(starts) == 1, starts
        built = Path(starts[0])
        assert built.parent.parent.parent == sandbox.clone / "untracked"
        assert built.parent.parent.name.startswith("venv-")

    def test_another_environments_venv_is_byte_for_byte_untouched(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        other = sandbox.other_view_venv()
        before = _snapshot(other)

        _context(sandbox.hook())
        sandbox.wait_for_build()
        assert "ENSURE_DAEMON_OK" in sandbox.hook().stdout

        assert _snapshot(other) == before

    def test_a_hook_during_the_build_says_it_is_running(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv(sleep=3)
        _context(sandbox.hook())
        context = _context(sandbox.hook())
        assert "already running" in context.lower(), context
        assert ".venv-bootstrap-" in context
        _assert_never_suggests_install_or_force(context)
        sandbox.wait_for_build()


class TestAFailedBuild:
    def test_is_reported_with_its_log_and_repair_and_is_not_respawned(
        self, sandbox: Sandbox
    ) -> None:
        sandbox.stub_uv(fail=True)
        _context(sandbox.hook())
        sandbox.wait_for_build()

        contexts = [_context(sandbox.hook()) for _ in range(3)]

        assert len(sandbox.uv_calls()) == 1, "a failed build must not respawn on every hook"
        for context in contexts:
            assert "failed" in context.lower(), context
            assert ".venv-bootstrap-" in context
            assert f"{sandbox.clone}/bin/hooks-daemon repair" in context
            _assert_never_suggests_install_or_force(context)


class TestARefusedBuildChangesNothing:
    def test_uv_missing_names_the_condition_and_its_fix(self, sandbox: Sandbox) -> None:
        other = sandbox.other_view_venv()
        before = _snapshot(sandbox.clone)
        other_before = _snapshot(other)

        context = _context(sandbox.hook())

        assert _snapshot(sandbox.clone) == before, "a refused build must change nothing"
        assert _snapshot(other) == other_before
        assert "uv:" in context, context
        assert "docs.astral.sh/uv" in context
        assert "nothing was changed" in context.lower()
        _assert_never_suggests_install_or_force(context)

    def test_the_opt_out_is_named_and_nothing_changes(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        before = _snapshot(sandbox.clone)

        context = _context(sandbox.hook(extra_env={"HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP": "1"}))

        assert "HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP" in context
        assert _snapshot(sandbox.clone) == before
        assert sandbox.uv_calls() == []


class TestNoBuildIsAttemptedWhereThe00454CasesSayDoNotTouch:
    def test_an_unreadable_clone_version_never_builds(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        (sandbox.clone / "src" / "claude_code_hooks_daemon" / "version.py").write_text("# cut\n")
        context = _context(sandbox.hook())
        assert sandbox.uv_calls() == []
        assert "damaged" in context.lower()
        assert "args=install" not in context.lower()

    def test_an_orphan_venv_without_a_clone_never_builds(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        sandbox.other_view_venv()
        (sandbox.clone / "scripts" / "lib" / "resolve_venv.sh").unlink()
        context = _context(sandbox.hook())
        assert sandbox.uv_calls() == []
        assert "install/force" in context.lower()

    def test_a_clone_without_the_driver_keeps_the_00454_message(self, sandbox: Sandbox) -> None:
        """A newer init.sh over an older clone: no crash, the upgrade advice."""
        sandbox.stub_uv()
        (sandbox.clone / "scripts" / "venv_bootstrap.sh").unlink()
        context = _context(sandbox.hook())
        assert f"args=upgrade {_CLONE_VERSION}" in context
        assert sandbox.uv_calls() == []


class TestTheStopFamilyAndTheFallbackEncoder:
    def test_stop_blocks_and_says_a_build_is_running(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv(sleep=3)
        _context(sandbox.hook())
        result = sandbox.hook(event="Stop")
        parsed = json.loads(result.stdout)
        assert parsed["decision"] == "block"
        reason = str(parsed["reason"]).lower()
        assert "venv" in reason and "build" in reason
        assert "not installed" not in reason
        sandbox.wait_for_build()

    def test_the_jq_less_encoder_carries_the_same_context(self, sandbox: Sandbox) -> None:
        with_jq = _context(sandbox.hook())
        (sandbox.root / "tools" / "jq").unlink()
        without_jq = _context(sandbox.hook())
        assert with_jq == without_jq
        assert "uv:" in without_jq


class TestTheHealthyPathIsUntouched:
    """Evaluated ONLY in the venv-missing branch: no added cost elsewhere."""

    def _plant_recording_driver(self, sandbox: Sandbox) -> Path:
        calls = sandbox.root / "driver-calls.log"
        driver = sandbox.clone / "scripts" / "venv_bootstrap.sh"
        driver.write_text(f'#!/bin/bash\necho "$*" >> "{calls}"\necho state=disabled\n')
        return calls

    def test_a_running_daemon_never_reaches_the_driver(self, sandbox: Sandbox) -> None:
        calls = self._plant_recording_driver(sandbox)
        init_sh = sandbox.project / ".claude" / "init.sh"
        result = subprocess.run(  # nosec B603 - fixed argv, no shell
            [
                BASH,
                "-c",
                f'source "{init_sh}"\nis_daemon_running() {{ return 0; }}\n'
                "ensure_daemon && echo OK",
            ],
            capture_output=True,
            text=True,
            env=sandbox.env(),
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        assert "OK" in result.stdout, result.stderr
        assert not calls.exists()

    def test_a_resolvable_venv_whose_daemon_fails_never_reaches_the_driver(
        self, sandbox: Sandbox
    ) -> None:
        sandbox.stub_uv()
        _context(sandbox.hook())
        sandbox.wait_for_build()
        calls = self._plant_recording_driver(sandbox)
        init_sh = sandbox.project / ".claude" / "init.sh"
        result = subprocess.run(  # nosec B603 - fixed argv, no shell
            [
                BASH,
                "-c",
                f'source "{init_sh}"\n'
                "_is_ci_environment() { return 1; }\n_is_ci_enforced() { return 1; }\n"
                "start_daemon() { validate_venv; return 1; }\n"
                'ensure_daemon || echo "missing=$_HOOKS_DAEMON_VENV_MISSING"',
            ],
            capture_output=True,
            text=True,
            env=sandbox.env(),
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        assert "missing=false" in result.stdout, result.stdout + result.stderr
        assert not calls.exists()
