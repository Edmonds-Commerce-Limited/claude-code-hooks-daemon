"""``scripts/venv_bootstrap.sh``: build a missing venv without the hook waiting (Plan 00456).

GitHub issue #53: a daemon clone shared by two environments (host and
container views of one bind-mounted project) has a venv for one of them only.
The other environment's hooks find the clone but no venv for their path. This
driver is what init.sh calls in that state (``hook``), and what
``bin/hooks-daemon repair`` calls before any venv exists (``repair``).

``hook`` must never block. The hook timeout is 60s and a real ``uv sync`` can
take longer, so the build runs DETACHED under the existing venv build lock
(Plan 00100 Phase 4). The hook takes the lock without waiting, hands it to
the detached child, and returns at once. A second hook finds the lock held and
starts nothing. A failed build leaves a marker keyed on the venv's own
fingerprint, and the hook does not respawn until the build's inputs change or
an explicit ``repair`` clears it.

Tests run the REAL driver against a tmp daemon dir holding only the data files
a clone contributes (``pyproject.toml``, ``uv.lock``, ``version.py``). The
driver finds its own libraries beside itself, exactly as it does in a clone. A
stub ``uv`` stands in for the build: it logs every call, can sleep so builds
overlap, can fail, and lays down a ``bin/python`` that execs this test's
interpreter, so the metadata write and the resolver see a working venv.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Final

import pytest

from tests.venv_bootstrap_sandbox import fake_clock_ahead

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DRIVER: Final[Path] = REPO_ROOT / "scripts" / "venv_bootstrap.sh"
BASH: Final[str] = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS: Final[int] = 60
_BUILD_WAIT_SECONDS: Final[float] = 30.0

_CLONE_VERSION: Final[str] = "3.61.0"
_OTHER_VIEW_VENV: Final[str] = "venv-home_dev_project_claude_hooks-daemon-py311-0badc0de"

#: Tools the driver and the libraries it sources need. `uv` is deliberately
#: absent: each test decides whether a stub is on PATH.
_TOOLS: Final[tuple[str, ...]] = (
    "bash",
    "sh",
    "env",
    "cat",
    "dirname",
    "basename",
    "mkdir",
    "rm",
    "mv",
    "touch",
    "chmod",
    "date",
    "sleep",
    "stat",
    "uname",
    "grep",
    "awk",
    "tr",
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
    "printf",
    "timeout",
    "cp",
)


def _daemon_dir(tmp_path: Path) -> Path:
    daemon_dir = tmp_path / "clone"
    daemon_dir.mkdir()
    (daemon_dir / "pyproject.toml").write_text(
        '[project]\nname = "fake-daemon"\nversion = "3.61.0"\nrequires-python = ">=3.11"\n'
    )
    (daemon_dir / "uv.lock").write_text("# lock v1\n")
    version_py = daemon_dir / "src" / "claude_code_hooks_daemon" / "version.py"
    version_py.parent.mkdir(parents=True)
    version_py.write_text(f'__version__ = "{_CLONE_VERSION}"\n')
    (daemon_dir / "untracked").mkdir()
    return daemon_dir


def _other_view_venv(daemon_dir: Path) -> Path:
    """Another environment's venv: a different slug, a dangling interpreter."""
    venv = daemon_dir / "untracked" / _OTHER_VIEW_VENV
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to("/nonexistent/host-only/python3.11")
    (venv / "pyvenv.cfg").write_text("home = /nonexistent/host-only\n")
    site = venv / "lib" / "python3.11" / "site-packages"
    site.mkdir(parents=True)
    (site / "_claude_code_hooks_daemon.pth").write_text(
        "/home/dev/project/.claude/hooks-daemon/src\n"
    )
    (venv / ".daemon-metadata.json").write_text('{"python_path": "x", "lock_hash": "y"}\n')
    return venv


def _snapshot(root: Path) -> dict[str, str]:
    """Every path under root with a digest of what it is: bytes, link, mode."""
    state: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in sorted(dirnames + filenames):
            path = Path(dirpath) / name
            rel = str(path.relative_to(root))
            st = path.lstat()
            if path.is_symlink():
                state[rel] = f"link:{path.readlink()}"
            elif path.is_dir():
                state[rel] = f"dir:{oct(st.st_mode)}"
            else:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                state[rel] = f"file:{oct(st.st_mode)}:{digest}"
    return state


def _stub_uv(tmp_path: Path, *, sleep: float = 0.0, fail: bool = False) -> Path:
    stub_dir = tmp_path / "uv-stub"
    stub_dir.mkdir(exist_ok=True)
    uv_log = tmp_path / "uv-calls.log"
    body = textwrap.dedent(f"""\
        #!/bin/bash
        echo "uv $* target=${{UV_PROJECT_ENVIRONMENT:-UNSET}}" >> "{uv_log}"
        sleep {sleep}
        if [ "{int(fail)}" = "1" ]; then
            echo "error: simulated resolver failure (network unreachable)" >&2
            exit 2
        fi
        mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
        printf '#!/bin/bash\\nexec "{sys.executable}" "$@"\\n' > "$UV_PROJECT_ENVIRONMENT/bin/python"
        chmod +x "$UV_PROJECT_ENVIRONMENT/bin/python"
        exit 0
        """)
    uv = stub_dir / "uv"
    uv.write_text(body)
    uv.chmod(0o755)
    return stub_dir


def _uv_calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "uv-calls.log"
    return [ln for ln in log.read_text().splitlines() if ln.strip()] if log.exists() else []


def _tool_dir(tmp_path: Path) -> Path:
    bindir = tmp_path / "tools"
    bindir.mkdir(exist_ok=True)
    for tool in _TOOLS:
        real = shutil.which(tool)
        if real is not None and not (bindir / tool).exists():
            (bindir / tool).symlink_to(real)
    return bindir


def _env(
    tmp_path: Path, *, with_uv: Path | None, extra: dict[str, str] | None = None
) -> dict[str, str]:
    path = [str(_tool_dir(tmp_path))]
    if with_uv is not None:
        path.insert(0, str(with_uv))
    env = {
        "PATH": ":".join(path),
        # venv.sh prepends $HOME/.local/bin, uv's default home. A tmp HOME
        # keeps this machine's real uv out of the picture.
        "HOME": str(tmp_path / "home"),
        # Deterministic interpreter: the gate and the build both use it.
        "HOOKS_DAEMON_PYTHON": sys.executable,
        "NO_COLOR": "1",
    }
    if extra:
        env.update(extra)
    return env


def _run(verb: str, daemon_dir: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 - fixed argv, no shell
        [BASH, str(DRIVER), verb, str(daemon_dir)],
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _fields(stdout: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in stdout.splitlines():
        key, sep, value = line.partition("=")
        assert sep, f"hook output must be key=value lines, got {line!r}"
        out.setdefault(key, []).append(value)
    return out


def _wait_for_lock_release(daemon_dir: Path) -> None:
    """The detached build holds the venv lock for exactly as long as it runs."""
    lock = daemon_dir / "untracked" / ".venv-bootstrap.lock"
    deadline = time.monotonic() + _BUILD_WAIT_SECONDS
    while time.monotonic() < deadline:
        probe = subprocess.run(  # nosec B603 - fixed argv, no shell
            ["flock", "-n", str(lock), "true"], capture_output=True, check=False
        )
        if probe.returncode == 0:
            return
        time.sleep(0.2)
    raise AssertionError("the detached build never released the venv lock")


def _resolves(daemon_dir: Path, env: dict[str, str]) -> bool:
    lib = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
    probe = subprocess.run(  # nosec B603 - fixed argv, no shell
        [BASH, str(lib), "python", str(daemon_dir)],
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    return probe.returncode == 0 and probe.stdout.strip() != ""


class TestTheHookStartsOneDetachedBuild:
    def test_all_green_starts_a_build_that_leaves_a_resolvable_venv(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path))

        started = time.monotonic()
        result = _run("hook", daemon_dir, env)
        elapsed = time.monotonic() - started

        assert result.returncode == 0, result.stderr
        out = _fields(result.stdout)
        assert out["state"] == ["started"], result.stdout
        log = Path(out["log"][0])
        assert log.parent == daemon_dir / "untracked"
        assert log.name.startswith(".venv-bootstrap-") and log.name.endswith(".log")
        assert elapsed < 10, f"the hook must not wait for the build ({elapsed:.1f}s)"

        _wait_for_lock_release(daemon_dir)
        assert len(_uv_calls(tmp_path)) == 1
        assert _resolves(daemon_dir, env), log.read_text()
        assert "succeeded" in log.read_text().lower()
        assert not list((daemon_dir / "untracked").glob(".venv-bootstrap-*.failed"))

    def test_the_hook_returns_before_a_slow_build_finishes(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path, sleep=5))

        started = time.monotonic()
        result = _run("hook", daemon_dir, env)
        elapsed = time.monotonic() - started

        assert _fields(result.stdout)["state"] == ["started"], result.stdout + result.stderr
        assert elapsed < 4, f"a 5s build must not hold the hook for {elapsed:.1f}s"
        _wait_for_lock_release(daemon_dir)
        assert _resolves(daemon_dir, env)

    def test_concurrent_hooks_start_exactly_one_build(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path, sleep=3))

        procs = [
            subprocess.Popen(  # nosec B603 - fixed argv, no shell
                [BASH, str(DRIVER), "hook", str(daemon_dir)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            for _ in range(6)
        ]
        states: list[str] = []
        for proc in procs:
            stdout, stderr = proc.communicate(timeout=_TIMEOUT_SECONDS)
            assert proc.returncode == 0, stderr
            states.extend(_fields(stdout)["state"])

        _wait_for_lock_release(daemon_dir)
        assert states.count("started") == 1, states
        assert set(states) <= {"started", "running"}, states
        assert len(_uv_calls(tmp_path)) == 1, _uv_calls(tmp_path)
        assert _resolves(daemon_dir, env)

    def test_a_hook_during_a_build_reports_running_and_names_the_log(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path, sleep=3))

        first = _fields(_run("hook", daemon_dir, env).stdout)
        second = _fields(_run("hook", daemon_dir, env).stdout)

        assert first["state"] == ["started"]
        assert second["state"] == ["running"]
        assert second["log"] == first["log"]
        _wait_for_lock_release(daemon_dir)
        assert len(_uv_calls(tmp_path)) == 1

    def test_another_environments_venv_is_byte_for_byte_untouched(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        other = _other_view_venv(daemon_dir)
        before = _snapshot(other)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path))

        assert _fields(_run("hook", daemon_dir, env).stdout)["state"] == ["started"]
        _wait_for_lock_release(daemon_dir)

        assert _resolves(daemon_dir, env)
        assert _snapshot(other) == before
        built = [
            p.name for p in (daemon_dir / "untracked").glob("venv-*") if p.name != _OTHER_VIEW_VENV
        ]
        assert len(built) == 1, built


class TestItRefusesAndChangesNothing:
    def test_uv_missing_is_refused_with_its_fix_and_zero_mutation(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        _other_view_venv(daemon_dir)
        before = _snapshot(daemon_dir)

        result = _run("hook", daemon_dir, _env(tmp_path, with_uv=None))

        assert result.returncode == 0, result.stderr
        out = _fields(result.stdout)
        assert out["state"] == ["refused"]
        assert out["missing"] == ["uv"]
        assert out["fix"][0].startswith("uv: ")
        assert "--force" not in result.stdout and "args=install" not in result.stdout
        assert _snapshot(daemon_dir) == before, "a refused gate must not create a single file"

    def test_no_compatible_python_is_refused_with_the_discovery_diagnostic(
        self, tmp_path: Path
    ) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        before = _snapshot(daemon_dir)
        bogus = tmp_path / "not-a-python"
        bogus.write_text("#!/bin/bash\nexit 1\n")
        bogus.chmod(0o755)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path), extra={"HOOKS_DAEMON_PYTHON": str(bogus)})

        out = _fields(_run("hook", daemon_dir, env).stdout)

        assert out["state"] == ["refused"]
        assert out["missing"] == ["compatible-python"]
        assert "HOOKS_DAEMON_PYTHON" in out["fix"][0]
        assert _snapshot(daemon_dir) == before
        assert _uv_calls(tmp_path) == []

    def test_the_opt_out_is_honoured_with_zero_mutation(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        before = _snapshot(daemon_dir)
        env = _env(
            tmp_path,
            with_uv=_stub_uv(tmp_path),
            extra={"HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP": "1"},
        )

        out = _fields(_run("hook", daemon_dir, env).stdout)

        assert out["state"] == ["disabled"]
        assert _snapshot(daemon_dir) == before
        assert _uv_calls(tmp_path) == []


class TestAFailedBuildIsRememberedNotRespawned:
    def _fail_once(self, tmp_path: Path) -> tuple[Path, dict[str, str], dict[str, list[str]]]:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path, fail=True))
        first = _fields(_run("hook", daemon_dir, env).stdout)
        assert first["state"] == ["started"]
        _wait_for_lock_release(daemon_dir)
        return daemon_dir, env, first

    def test_the_next_hook_reports_failed_with_the_log_and_does_not_respawn(
        self, tmp_path: Path
    ) -> None:
        daemon_dir, env, first = self._fail_once(tmp_path)
        log = Path(first["log"][0])
        assert "network unreachable" in log.read_text(), "uv's own error must reach the log"

        for _ in range(3):
            out = _fields(_run("hook", daemon_dir, env).stdout)
            assert out["state"] == ["failed"], out
            assert out["log"] == first["log"]

        assert len(_uv_calls(tmp_path)) == 1, "a failed build must not be retried on every hook"
        assert not _resolves(daemon_dir, env)

    def test_changed_inputs_allow_one_retry(self, tmp_path: Path) -> None:
        daemon_dir, env, _ = self._fail_once(tmp_path)
        (daemon_dir / "uv.lock").write_text("# lock v2, the fix\n")

        out = _fields(_run("hook", daemon_dir, env).stdout)

        assert out["state"] == ["started"]
        _wait_for_lock_release(daemon_dir)
        assert len(_uv_calls(tmp_path)) == 2

    def test_a_build_whose_venv_does_not_resolve_counts_as_failed(self, tmp_path: Path) -> None:
        """uv can exit 0 and still leave nothing the resolver accepts: success is
        judged by the resolver, not by ensure_venv's exit code."""
        daemon_dir = _daemon_dir(tmp_path)
        stub_dir = tmp_path / "uv-stub"
        stub_dir.mkdir()
        (stub_dir / "uv").write_text(
            f'#!/bin/bash\necho "uv $*" >> "{tmp_path / "uv-calls.log"}"\nexit 0\n'
        )
        (stub_dir / "uv").chmod(0o755)
        env = _env(tmp_path, with_uv=stub_dir)

        assert _fields(_run("hook", daemon_dir, env).stdout)["state"] == ["started"]
        _wait_for_lock_release(daemon_dir)

        out = _fields(_run("hook", daemon_dir, env).stdout)
        assert out["state"] == ["failed"]
        assert len(_uv_calls(tmp_path)) == 1


class TestRepairBuildsInTheForeground:
    def test_repair_builds_clears_the_failed_marker_and_exits_zero(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        failing = _env(tmp_path, with_uv=_stub_uv(tmp_path, fail=True))
        assert _fields(_run("hook", daemon_dir, failing).stdout)["state"] == ["started"]
        _wait_for_lock_release(daemon_dir)
        assert list((daemon_dir / "untracked").glob(".venv-bootstrap-*.failed"))

        working = _env(tmp_path, with_uv=_stub_uv(tmp_path))
        result = _run("repair", daemon_dir, working)

        assert result.returncode == 0, result.stdout + result.stderr
        assert _resolves(daemon_dir, working)
        assert not list((daemon_dir / "untracked").glob(".venv-bootstrap-*.failed"))

    def test_repair_with_uv_missing_names_it_and_changes_nothing(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        before = _snapshot(daemon_dir)

        result = _run("repair", daemon_dir, _env(tmp_path, with_uv=None))

        assert result.returncode == 1
        assert "uv" in result.stderr
        assert _snapshot(daemon_dir) == before

    def test_repair_waits_for_a_background_build_and_reuses_it(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path, sleep=2))
        assert _fields(_run("hook", daemon_dir, env).stdout)["state"] == ["started"]

        result = _run("repair", daemon_dir, env)

        assert result.returncode == 0, result.stderr
        assert len(_uv_calls(tmp_path)) == 1, "repair must reuse the build it waited for"


def _markers(daemon_dir: Path) -> list[Path]:
    return sorted((daemon_dir / "untracked").glob(".venv-bootstrap-*.failed"))


def _wait_for_path_gone(path: Path) -> None:
    deadline = time.monotonic() + _BUILD_WAIT_SECONDS
    while time.monotonic() < deadline:
        if not path.exists():
            return
        time.sleep(0.2)
    raise AssertionError(f"{path} was never removed")


def _source_venv_sh(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run ``script`` in bash with scripts/install/venv.sh sourced."""
    venv_sh = REPO_ROOT / "scripts" / "install" / "venv.sh"
    return subprocess.run(  # nosec B603 - fixed argv, no shell
        [BASH, "-c", f'set -euo pipefail\nsource "{venv_sh}"\n{script}'],
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


class TestSwitchedOffMeansSwitchedOff:
    """Review B1: ensure_venv skips on HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1 AND on
    CI=true. The hook must refuse on both, naming which, and an explicit
    ``repair`` is a deliberate request that builds regardless. A skipped build
    is never recorded as a failed one."""

    def test_ci_true_is_reported_as_disabled_and_names_the_variable(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        before = _snapshot(daemon_dir)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path), extra={"CI": "true"})

        out = _fields(_run("hook", daemon_dir, env).stdout)

        assert out["state"] == ["disabled"], out
        assert out["detail"] == ["CI=true"]
        assert _snapshot(daemon_dir) == before
        assert _uv_calls(tmp_path) == []

    def test_the_opt_out_names_its_variable(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(
            tmp_path, with_uv=_stub_uv(tmp_path), extra={"HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP": "1"}
        )

        out = _fields(_run("hook", daemon_dir, env).stdout)

        assert out["detail"] == ["HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1"]

    @pytest.mark.parametrize(
        "switch", [{"HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP": "1"}, {"CI": "true"}], ids=["opt-out", "ci"]
    )
    def test_an_explicit_repair_builds_regardless(
        self, tmp_path: Path, switch: dict[str, str]
    ) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path), extra=switch)

        result = _run("repair", daemon_dir, env)

        assert result.returncode == 0, result.stdout + result.stderr
        assert _resolves(daemon_dir, env)
        assert len(_uv_calls(tmp_path)) == 1
        assert _markers(daemon_dir) == []
        name = next(iter(switch))
        assert name in result.stderr, "the override must be announced, naming the variable"

    def test_a_switched_off_build_child_writes_no_failed_marker(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        lock_dir = daemon_dir / "untracked" / ".venv-bootstrap.lock.d"
        lock_dir.mkdir()
        env = _env(
            tmp_path,
            with_uv=_stub_uv(tmp_path),
            extra={
                "CI": "true",
                "HOOKS_DAEMON_VENV_LOCK_BACKEND": "mkdir",
                "HOOKS_DAEMON_VENV_LOCK_INHERITED": f"mkdir:{lock_dir}",
            },
        )

        result = subprocess.run(  # nosec B603 - fixed argv, no shell
            [BASH, str(DRIVER), "build", str(daemon_dir), sys.executable, "fp", "inputs"],
            capture_output=True,
            text=True,
            env=env,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )

        assert result.returncode != 0
        assert "CI=true" in result.stderr
        assert _markers(daemon_dir) == []
        assert _uv_calls(tmp_path) == []
        assert not lock_dir.exists(), "the adopted lock is still released"


class TestADetachedBuildIsBoundedAndNamed:
    """Review I1: a hung build must not hold the lock for ever, and the
    process holding it must be findable."""

    def test_a_build_past_its_bound_ends_failed_and_is_reported(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(
            tmp_path,
            with_uv=_stub_uv(tmp_path, sleep=30),
            extra={"HOOKS_DAEMON_VENV_BUILD_TIMEOUT": "2"},
        )

        first = _fields(_run("hook", daemon_dir, env).stdout)
        assert first["state"] == ["started"]
        _wait_for_lock_release(daemon_dir)

        assert len(_markers(daemon_dir)) == 1
        assert "timed out" in Path(first["log"][0]).read_text()
        out = _fields(_run("hook", daemon_dir, env).stdout)
        assert out["state"] == ["failed"]
        assert len(_uv_calls(tmp_path)) == 1

    def test_running_names_the_live_build_pid_and_its_age(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path, sleep=4))
        assert _fields(_run("hook", daemon_dir, env).stdout)["state"] == ["started"]
        time.sleep(1)

        out = _fields(_run("hook", daemon_dir, env).stdout)

        assert out["state"] == ["running"]
        pid = int(out["pid"][0])
        os.kill(pid, 0)
        assert int(out["elapsed"][0]) >= 0
        log = Path(out["log"][0])
        assert f"pid {pid}" in log.read_text(), "the log names the build's pid"
        _wait_for_lock_release(daemon_dir)


def _strays(pattern: str) -> list[str]:
    """Processes whose whole command line is ``pattern`` (pgrep excludes itself)."""
    probe = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["pgrep", "-fx", pattern], capture_output=True, text=True, check=False
    )
    return probe.stdout.split()


class TestOnlyATimeoutIsATimeout:
    """Re-review N2: a shutdown or a manual ``kill`` of the running pid is not
    a timeout. It records no failure, so the next hook retries."""

    def test_a_term_inside_the_bound_records_no_failure_and_allows_retry(
        self, tmp_path: Path
    ) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path, sleep=5))
        first = _fields(_run("hook", daemon_dir, env).stdout)
        time.sleep(1)
        pid = int(_fields(_run("hook", daemon_dir, env).stdout)["pid"][0])

        os.kill(pid, signal.SIGTERM)
        _wait_for_lock_release(daemon_dir)

        log = Path(first["log"][0]).read_text()
        assert _markers(daemon_dir) == [], log
        assert "timed out" not in log
        assert "stopped by a signal" in log
        assert _fields(_run("hook", daemon_dir, env).stdout)["state"] == ["started"]
        _wait_for_lock_release(daemon_dir)

    def test_a_stop_after_the_venv_resolves_is_not_a_failure(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path))
        assert _run("repair", daemon_dir, env).returncode == 0
        assert _resolves(daemon_dir, env)

        judged = subprocess.run(  # nosec B603 - fixed argv, no shell
            [
                BASH,
                "-c",
                f'source "{DRIVER}"\n'
                f'_VB_CHILD_DAEMON_DIR="{daemon_dir}"\n'
                f'_VB_CHILD_MARKER="{daemon_dir}/untracked/.venv-bootstrap-fp.failed"\n'
                "_VB_CHILD_INPUTS=inputs\n_VB_CHILD_STARTED=1\n_VB_CHILD_BOUND=1\n"
                "_vb_judge_stop 143",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )

        assert judged.returncode == 0, judged.stderr
        assert _markers(daemon_dir) == []
        assert "timed out" not in judged.stderr


class TestTheBoundHoldsWithoutTimeout:
    """Re-review N3: stock macOS has no ``timeout``, ``setsid`` or ``flock``.
    The bound must still hold there, or the heartbeat keeps a hung build's
    lock fresh for ever."""

    def test_a_hung_build_ends_failed_with_no_timeout_binary(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(
            tmp_path,
            with_uv=_stub_uv(tmp_path, sleep=60),
            extra={
                "HOOKS_DAEMON_VENV_BUILD_TIMEOUT": "2",
                "HOOKS_DAEMON_VENV_LOCK_HEARTBEAT_SECONDS": "1",
            },
        )
        for tool in ("timeout", "setsid", "flock"):
            (tmp_path / "tools" / tool).unlink()

        first = _fields(_run("hook", daemon_dir, env).stdout)
        assert first["state"] == ["started"]
        _wait_for_path_gone(daemon_dir / "untracked" / ".venv-bootstrap.lock.d")

        assert len(_markers(daemon_dir)) == 1
        assert "timed out after 2s" in Path(first["log"][0]).read_text()
        assert _fields(_run("hook", daemon_dir, env).stdout)["state"] == ["failed"]


class TestNoStrayHeartbeats:
    """Re-review N6: a heartbeat is only for a holder that keeps the lock, and
    stopping one stops its ``sleep`` too."""

    def test_failed_state_hooks_start_no_heartbeat(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(
            tmp_path,
            with_uv=_stub_uv(tmp_path, fail=True),
            extra={
                "HOOKS_DAEMON_VENV_LOCK_BACKEND": "mkdir",
                "HOOKS_DAEMON_VENV_LOCK_HEARTBEAT_SECONDS": "97",
            },
        )
        assert _fields(_run("hook", daemon_dir, env).stdout)["state"] == ["started"]
        _wait_for_path_gone(daemon_dir / "untracked" / ".venv-bootstrap.lock.d")

        for _ in range(3):
            assert _fields(_run("hook", daemon_dir, env).stdout)["state"] == ["failed"]

        assert _strays("sleep 97") == []

    def test_release_stops_the_heartbeat_and_its_sleep(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(
            tmp_path,
            with_uv=None,
            extra={
                "HOOKS_DAEMON_VENV_LOCK_BACKEND": "mkdir",
                "HOOKS_DAEMON_VENV_LOCK_HEARTBEAT_SECONDS": "89",
            },
        )

        result = _source_venv_sh(
            # The heartbeat must be asleep when the release comes.
            f'acquire_venv_lock "{daemon_dir}"\nsleep 1\nrelease_venv_lock\nsleep 0.5',
            env,
        )

        assert result.returncode == 0, result.stderr
        assert _strays("sleep 89") == []


def _build_processes(daemon_dir: Path) -> list[int]:
    """Live (non-zombie) processes of this daemon dir's detached build, read from /proc."""
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
            state = (entry / "stat").read_text().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            continue  # it exited between the listing and the read
        if state != "Z" and b"build" in argv and any(bytes(daemon_dir) in a for a in argv):
            found.append(int(entry.name))
    return found


#: The watchdog checks on its build process once a second.
_WATCHDOG_POLL_SECONDS: Final[float] = 1.0


@pytest.mark.skipif(not Path("/proc/self/cmdline").is_file(), reason="reads /proc")
class TestTheWatchdogNeverOutlivesItsBuild:
    """Final review N7: a KILL of the build process runs no trap. Its watchdog
    must notice within one poll and exit having signalled nothing, because by
    the bound the build's process group id may belong to someone else."""

    def test_a_killed_build_process_takes_its_watchdog_with_it(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(
            tmp_path,
            with_uv=_stub_uv(tmp_path, sleep=2),
            extra={"HOOKS_DAEMON_VENV_BUILD_TIMEOUT": "6"},
        )
        started = time.monotonic()
        first = _fields(_run("hook", daemon_dir, env).stdout)
        time.sleep(0.7)
        build_pid = int(_fields(_run("hook", daemon_dir, env).stdout)["pid"][0])

        os.kill(build_pid, signal.SIGKILL)

        # The orphaned job finishes its 2s uv run; the watchdog must be gone
        # one poll after the KILL, well inside the 6s bound.
        deadline = time.monotonic() + 2 + _WATCHDOG_POLL_SECONDS + 1.5
        while _build_processes(daemon_dir) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert _build_processes(daemon_dir) == []
        assert time.monotonic() - started < 6, "the check must land before the bound"

        time.sleep(max(0.0, started + 7.5 - time.monotonic()))
        log = Path(first["log"][0]).read_text()
        assert "reached its" not in log, log
        assert _resolves(daemon_dir, env)

    def test_a_build_that_ignores_term_is_killed_after_the_grace(self, tmp_path: Path) -> None:
        stopped = subprocess.run(  # nosec B603 - fixed argv, no shell
            [
                BASH,
                "-c",
                f'source "{DRIVER}"\n'
                "set -m\n"
                '( trap "" TERM; sleep 30 ) < /dev/null &\n'
                'job="$!"\n'
                "set +m\n"
                "sleep 0.3\n"
                'echo "job=$job"\n'
                "status=0\n"
                '_vb_stop_job "$job" 1 || status=$?\n'
                'echo "status=$status"',
            ],
            capture_output=True,
            text=True,
            env=_env(tmp_path, with_uv=None),
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )

        fields = _fields(stopped.stdout)
        assert fields["status"] == ["137"], stopped.stderr
        with pytest.raises(ProcessLookupError):
            os.killpg(int(fields["job"][0]), 0)


class TestStalenessIsJudgedByTheFilesystemClock:
    """Final review N9: a host and a container (or VM) sharing the lock can run
    clocks minutes apart. A reader whose clock runs ahead must not read a live
    holder's fresh lock as stale."""

    _PROBE: Final[str] = (
        'if age="$(_venv_mkdir_lock_is_stale "{lock}")"; then echo "stale=$age"; '
        'else echo "stale=no"; fi'
    )

    def _judge(self, tmp_path: Path, lock_dir: Path) -> str:
        env = _env(tmp_path, with_uv=None, extra={"HOOKS_DAEMON_VENV_LOCK_STALE_SECONDS": "600"})
        fake_clock_ahead(tmp_path / "tools", 1000)
        result = _source_venv_sh(self._PROBE.format(lock=lock_dir), env)
        assert result.returncode == 0, result.stderr
        return _fields(result.stdout)["stale"][0]

    def test_a_fresh_lock_is_live_to_a_reader_whose_clock_runs_ahead(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "untracked" / ".venv-bootstrap.lock.d"
        lock_dir.mkdir(parents=True)

        assert self._judge(tmp_path, lock_dir) == "no"
        assert [p.name for p in lock_dir.parent.iterdir()] == [lock_dir.name], "probe left behind"

    def test_a_silent_lock_is_still_stale(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "untracked" / ".venv-bootstrap.lock.d"
        lock_dir.mkdir(parents=True)
        silent_since = time.time() - 1000
        os.utime(lock_dir, (silent_since, silent_since))

        age = self._judge(tmp_path, lock_dir)

        assert age != "no" and int(age) >= 1000


class TestRepairWaitsOutAHookStartedBuild:
    """Review I4: repair, the skill and upgrade must not give up at the 120s lock
    bound behind a build a hook started; they wait for that build's own bound."""

    def test_repair_outwaits_the_generic_lock_bound(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(
            tmp_path,
            with_uv=_stub_uv(tmp_path, sleep=4),
            extra={"HOOKS_DAEMON_VENV_LOCK_TIMEOUT": "1"},
        )
        assert _fields(_run("hook", daemon_dir, env).stdout)["state"] == ["started"]

        result = _run("repair", daemon_dir, env)

        assert result.returncode == 0, result.stdout + result.stderr
        assert len(_uv_calls(tmp_path)) == 1, "repair must reuse the build it waited for"


class TestTheMkdirLockSurvivesALongBuild:
    """Review I2: without flock, lock staleness is judged by age. A live build
    must keep its lock fresh, and a holder only ever removes its own lock."""

    def _env(self, tmp_path: Path, *, sleep: float) -> dict[str, str]:
        return _env(
            tmp_path,
            with_uv=_stub_uv(tmp_path, sleep=sleep),
            extra={
                "HOOKS_DAEMON_VENV_LOCK_BACKEND": "mkdir",
                "HOOKS_DAEMON_VENV_LOCK_STALE_SECONDS": "3",
                "HOOKS_DAEMON_VENV_LOCK_HEARTBEAT_SECONDS": "1",
            },
        )

    def test_a_build_older_than_the_stale_age_is_still_running(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = self._env(tmp_path, sleep=7)
        lock_dir = daemon_dir / "untracked" / ".venv-bootstrap.lock.d"

        assert _fields(_run("hook", daemon_dir, env).stdout)["state"] == ["started"]
        time.sleep(5)
        second = _fields(_run("hook", daemon_dir, env).stdout)

        assert second["state"] == ["running"], second
        _wait_for_path_gone(lock_dir)
        assert len(_uv_calls(tmp_path)) == 1
        assert _resolves(daemon_dir, env)

    def test_release_leaves_a_lock_another_process_now_holds(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "lock.d"
        lock_dir.mkdir()
        (lock_dir / "pid").write_text("999999\n")

        result = _source_venv_sh(
            f'_VENV_LOCK_BACKEND=mkdir\n_VENV_LOCK_DIR="{lock_dir}"\nrelease_venv_lock',
            _env(tmp_path, with_uv=None),
        )

        assert result.returncode == 0, result.stderr
        assert lock_dir.is_dir(), "a lock whose pid is not ours must not be removed"


class TestAdoptionOnlyTakesTheRealLock:
    """Review S5: the inherited spec is an environment variable; a mkdir spec
    naming any other directory must not be adopted (and later rm -rf'd)."""

    def test_a_foreign_directory_is_refused_and_untouched(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        foreign = tmp_path / "precious"
        foreign.mkdir()
        before = _snapshot(foreign)
        env = _env(
            tmp_path,
            with_uv=None,
            extra={"HOOKS_DAEMON_VENV_LOCK_INHERITED": f"mkdir:{foreign}"},
        )

        result = _source_venv_sh(f'adopt_venv_lock "{daemon_dir}"', env)

        assert result.returncode != 0
        assert _snapshot(foreign) == before


class TestTheFailedMarkerIsJudgedUnderTheLock:
    """Review I6: a build can fail and write its marker between a hook's marker
    check and its lock acquire. Judged under the lock, that hook reports the
    failure instead of deleting the fresh marker and retrying."""

    def test_a_marker_written_just_before_the_acquire_is_honoured(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        real_flock = shutil.which("flock")
        assert real_flock is not None
        tools = tmp_path / "tools"
        tools.mkdir()
        saved = tmp_path / "saved-marker"
        calls = tmp_path / "flock-calls"
        # The driver's second flock call is its lock acquire: plant the
        # failed build's marker right then, as a racing build would.
        (tools / "flock").write_text(textwrap.dedent(f"""\
            #!/bin/bash
            n=0
            if [ -f "{calls}" ]; then n="$(cat "{calls}")"; fi
            n=$((n + 1))
            echo "$n" > "{calls}"
            if [ "$n" -eq 2 ] && [ -f "{saved}" ]; then
                cp "{saved}" "$(cat "{tmp_path / 'marker-path'}")"
            fi
            exec "{real_flock}" "$@"
            """))
        (tools / "flock").chmod(0o755)
        failing = _env(tmp_path, with_uv=_stub_uv(tmp_path, fail=True))
        assert _fields(_run("hook", daemon_dir, failing).stdout)["state"] == ["started"]
        _wait_for_lock_release(daemon_dir)
        [marker] = _markers(daemon_dir)
        shutil.copy2(marker, saved)
        (tmp_path / "marker-path").write_text(str(marker))
        marker.unlink()
        calls.unlink()

        out = _fields(_run("hook", daemon_dir, failing).stdout)

        assert out["state"] == ["failed"], out
        assert len(_uv_calls(tmp_path)) == 1, "the racing hook must not retry the build"
        assert marker.is_file()


class TestUsage:
    def test_an_unknown_verb_is_a_usage_error(self, tmp_path: Path) -> None:
        result = _run("explode", _daemon_dir(tmp_path), _env(tmp_path, with_uv=None))
        assert result.returncode == 2
        assert "usage" in result.stderr.lower()

    @pytest.mark.parametrize("verb", ["hook", "repair"])
    def test_a_missing_daemon_dir_is_a_usage_error(self, tmp_path: Path, verb: str) -> None:
        result = _run(verb, tmp_path / "absent", _env(tmp_path, with_uv=None))
        assert result.returncode == 2
