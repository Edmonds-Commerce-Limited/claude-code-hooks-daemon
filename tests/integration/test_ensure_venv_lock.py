"""Plan 00100 Phase 4 (Plan 00362 Task 2.10, defect D4): venv mutation is serialised.

Two daemons starting at once (a host shell and a container, or two terminals
in one project) both reach the slow path of ``ensure_venv`` in
``scripts/install/venv.sh``: each decides the venv is missing or stale, each
``rm -rf``s it and each runs ``uv sync`` into the same directory. The second
starter's ``rm -rf`` lands while the first's ``uv sync`` is mid-copy, and the
survivor is a venv neither of them built.

The fix: the slow path runs under a lock on
``{daemon_dir}/untracked/.venv-bootstrap.lock``. The first starter builds;
the second waits for it (bounded, with a message naming the lock), then
re-checks freshness and REUSES the finished venv instead of rebuilding. When
``flock`` is not installed, or ``HOOKS_DAEMON_VENV_LOCK_BACKEND=mkdir`` is
set, a ``mkdir``-based lock with a stale-age check stands in.

Task 4.0's spike (recorded in Plan 00100) showed ``flock(2)`` holds across
processes sharing this project's Podman bind mount, so ``flock`` is the
default backend and ``mkdir`` is the fallback, not the other way round.

Tests drive the bash function through ``subprocess`` with a stub ``uv`` on
PATH, in the same shape as ``test_venv_sh_container_proactive_copy.py``: the
stub logs every invocation and sleeps so two starters genuinely overlap, and
it creates ``bin/python`` so the stamp fast path recognises the result. No
real ``uv sync`` runs, so the interleaving is deterministic and quick.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_SH = REPO_ROOT / "scripts" / "install" / "venv.sh"
FP_SH = REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"
BASH = shutil.which("bash") or "/bin/bash"

#: ``ensure_venv`` skips entirely when either is set (GitHub Actions exports
#: ``CI=true``), so both are dropped from the inherited environment.
_GATE_VARS: Final[tuple[str, ...]] = ("CI", "HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP")

LOCK_FILE_NAME: Final[str] = ".venv-bootstrap.lock"
#: Production-truth fragments of the lock's three user-facing messages.
WAITING_FRAGMENT: Final[str] = "waiting up to"
TIMEOUT_FRAGMENT: Final[str] = "gave up waiting for the venv lock"
STALE_FRAGMENT: Final[str] = "stale venv lock"

_TIMEOUT_SECONDS = 60


def _write_stub_uv(tmp_path: Path, uv_log: Path, sleep_seconds: float) -> Path:
    """PATH dir with a stub ``uv`` that logs, sleeps, and lays down bin/python.

    The sleep is what makes two starters overlap: with the real ``uv`` the
    window is real but its width is whatever the package cache makes it.
    """
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir(exist_ok=True)
    uv_stub = stub_dir / "uv"
    uv_stub.write_text(
        textwrap.dedent(f"""\
        #!/bin/bash
        echo "uv_sync pid=$$ target=${{UV_PROJECT_ENVIRONMENT:-UNSET}}" >> "{uv_log}"
        sleep {sleep_seconds}
        if [ -n "${{UV_PROJECT_ENVIRONMENT:-}}" ]; then
            mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
            : > "$UV_PROJECT_ENVIRONMENT/bin/python"
            chmod +x "$UV_PROJECT_ENVIRONMENT/bin/python"
        fi
        exit 0
        """)
    )
    uv_stub.chmod(0o755)
    return stub_dir


def _daemon_dir(tmp_path: Path, name: str = "project") -> Path:
    daemon_dir = tmp_path / name
    daemon_dir.mkdir()
    (daemon_dir / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.0.0"\n')
    return daemon_dir


def _env(stub_dir: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _GATE_VARS}
    env["NO_COLOR"] = "1"
    # The stub dir is exported inside the harness AFTER sourcing venv.sh
    # (which prepends ~/.local/bin); it is carried in via this variable.
    env["STUB_DIR"] = str(stub_dir)
    if extra:
        env.update(extra)
    return env


def _harness(daemon_dir: Path) -> str:
    return textwrap.dedent(f"""\
        set -euo pipefail
        . "{VENV_SH}"
        . "{FP_SH}"
        export PATH="$STUB_DIR:$PATH"
        ensure_venv "{daemon_dir}" "v99.0.0" "{sys.executable}"
        """)


def _start(daemon_dir: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [BASH, "-c", _harness(daemon_dir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def _finish(proc: subprocess.Popen[str]) -> tuple[int, str, str]:
    out, err = proc.communicate(timeout=_TIMEOUT_SECONDS)
    return proc.returncode, out, err


def _uv_calls(uv_log: Path) -> list[str]:
    if not uv_log.exists():
        return []
    return [ln for ln in uv_log.read_text().splitlines() if ln.strip()]


def _fingerprint(daemon_dir: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        [BASH, "-c", f'. "{FP_SH}"; python_venv_fingerprint "{sys.executable}" "{daemon_dir}"'],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _hold_lock(lock_file: Path, seconds: int) -> subprocess.Popen[str]:
    """Hold an flock on ``lock_file`` from a separate process for ``seconds``."""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    script = f'exec 9>"{lock_file}"; flock 9; echo held; sleep {seconds}'
    proc = subprocess.Popen(
        [BASH, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "held"
    return proc


def _run_two_starters(
    tmp_path: Path, extra_env: dict[str, str] | None = None
) -> tuple[tuple[int, str, str], tuple[int, str, str], list[str], Path]:
    """Start two ``ensure_venv`` calls 0.3s apart against one daemon_dir."""
    daemon_dir = _daemon_dir(tmp_path)
    uv_log = tmp_path / "uv_calls.log"
    stub_dir = _write_stub_uv(tmp_path, uv_log, sleep_seconds=1.5)
    env = _env(stub_dir, extra_env)

    first = _start(daemon_dir, env)
    time.sleep(0.3)
    second = _start(daemon_dir, env)
    return _finish(first), _finish(second), _uv_calls(uv_log), daemon_dir


class TestConcurrentStartersBuildOnce:
    """Task 4.1: two simultaneous ``ensure_venv`` calls do not corrupt the venv."""

    def test_second_starter_waits_then_reuses_the_finished_venv(self, tmp_path: Path) -> None:
        (rc1, out1, err1), (rc2, out2, err2), calls, daemon_dir = _run_two_starters(tmp_path)

        assert rc1 == 0, f"first starter failed:\n{err1}"
        assert rc2 == 0, f"second starter failed:\n{err2}"
        assert out1.strip() == out2.strip(), (
            f"both starters must report the same venv path: {out1!r} vs {out2!r}"
        )
        assert len(calls) == 1, (
            f"exactly ONE uv sync must run for two concurrent starters; got {calls}"
        )
        assert WAITING_FRAGMENT in err2, (
            f"the second starter must say it is waiting on the lock; stderr:\n{err2}"
        )
        assert WAITING_FRAGMENT not in err1, (
            f"the first starter took the lock uncontended and must not claim to wait:\n{err1}"
        )
        venv_path = Path(out1.strip())
        assert (venv_path / "bin" / "python").exists()
        assert (venv_path / ".daemon-version").read_text().strip() == "v99.0.0"
        assert (daemon_dir / "untracked" / LOCK_FILE_NAME).exists(), (
            "the lock file must live beside the venv, under untracked/"
        )

    @pytest.mark.slow
    def test_twenty_iterations_never_double_build(self, tmp_path: Path) -> None:
        """Plan 00100 Phase 4 success gate: deterministic over 20 iterations."""
        uv_log = tmp_path / "uv_calls.log"
        stub_dir = _write_stub_uv(tmp_path, uv_log, sleep_seconds=0.4)
        env = _env(stub_dir)
        for i in range(20):
            daemon_dir = _daemon_dir(tmp_path, name=f"project-{i}")
            uv_log.write_text("")
            first = _start(daemon_dir, env)
            second = _start(daemon_dir, env)
            rc1, _, err1 = _finish(first)
            rc2, _, err2 = _finish(second)
            assert rc1 == 0 and rc2 == 0, f"iteration {i}:\n{err1}\n{err2}"
            calls = _uv_calls(uv_log)
            assert len(calls) == 1, f"iteration {i}: {len(calls)} uv syncs ran: {calls}"


class TestLockWaitIsBounded:
    """Task 4.2: a held lock is waited on for a bounded time, then reported clearly."""

    def test_gives_up_with_a_message_naming_the_lock_file(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        lock_file = daemon_dir / "untracked" / LOCK_FILE_NAME
        holder = _hold_lock(lock_file, seconds=30)
        try:
            uv_log = tmp_path / "uv_calls.log"
            stub_dir = _write_stub_uv(tmp_path, uv_log, sleep_seconds=0)
            env = _env(stub_dir, {"HOOKS_DAEMON_VENV_LOCK_TIMEOUT": "1"})
            started = time.monotonic()
            rc, _out, err = _finish(_start(daemon_dir, env))
            elapsed = time.monotonic() - started
        finally:
            holder.kill()
            holder.wait()

        assert rc != 0, "a lock that never frees must be a failure, not a silent build"
        assert TIMEOUT_FRAGMENT in err, f"timeout must be named; stderr:\n{err}"
        assert str(lock_file) in err, f"the lock file path must be named; stderr:\n{err}"
        assert "1s" in err, f"the bound waited must be stated; stderr:\n{err}"
        assert elapsed < 15, f"a 1s bound must not wait {elapsed:.1f}s"
        assert _uv_calls(uv_log) == [], "no uv sync may run while the lock is held"

    def test_fast_path_does_not_need_the_lock(self, tmp_path: Path) -> None:
        """A fresh venv is reused without touching the lock — a starter that has
        nothing to build must not queue behind one that does."""
        daemon_dir = _daemon_dir(tmp_path)
        uv_log = tmp_path / "uv_calls.log"
        stub_dir = _write_stub_uv(tmp_path, uv_log, sleep_seconds=0)
        env = _env(stub_dir, {"HOOKS_DAEMON_VENV_LOCK_TIMEOUT": "1"})
        rc, out, err = _finish(_start(daemon_dir, env))
        assert rc == 0, err
        assert len(_uv_calls(uv_log)) == 1

        lock_file = daemon_dir / "untracked" / LOCK_FILE_NAME
        holder = _hold_lock(lock_file, seconds=30)
        try:
            rc, out2, err2 = _finish(_start(daemon_dir, env))
        finally:
            holder.kill()
            holder.wait()
        assert rc == 0, f"fast path must succeed while the lock is held:\n{err2}"
        assert out2.strip() == out.strip()
        assert WAITING_FRAGMENT not in err2 and TIMEOUT_FRAGMENT not in err2, err2
        assert len(_uv_calls(uv_log)) == 1, "fast path must not rebuild"


class TestMkdirFallback:
    """Task 4.0 fallback: without ``flock`` a ``mkdir`` lock with stale-age check."""

    def test_two_starters_build_once(self, tmp_path: Path) -> None:
        (rc1, out1, err1), (rc2, out2, err2), calls, _ = _run_two_starters(
            tmp_path, {"HOOKS_DAEMON_VENV_LOCK_BACKEND": "mkdir"}
        )
        assert rc1 == 0, err1
        assert rc2 == 0, err2
        assert out1.strip() == out2.strip()
        assert len(calls) == 1, f"mkdir backend must also serialise: {calls}"
        assert WAITING_FRAGMENT in err2, err2

    def test_fresh_lock_dir_is_waited_on_then_reported(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        lock_dir = daemon_dir / "untracked" / f"{LOCK_FILE_NAME}.d"
        lock_dir.mkdir(parents=True)
        uv_log = tmp_path / "uv_calls.log"
        stub_dir = _write_stub_uv(tmp_path, uv_log, sleep_seconds=0)
        env = _env(
            stub_dir,
            {"HOOKS_DAEMON_VENV_LOCK_BACKEND": "mkdir", "HOOKS_DAEMON_VENV_LOCK_TIMEOUT": "1"},
        )
        rc, _out, err = _finish(_start(daemon_dir, env))
        assert rc != 0
        assert TIMEOUT_FRAGMENT in err, err
        assert str(lock_dir) in err, err
        assert _uv_calls(uv_log) == []

    def test_stale_lock_dir_is_reclaimed(self, tmp_path: Path) -> None:
        """A lock dir older than the stale threshold belongs to a starter that
        died without releasing; it is removed, announced, and the build proceeds."""
        daemon_dir = _daemon_dir(tmp_path)
        lock_dir = daemon_dir / "untracked" / f"{LOCK_FILE_NAME}.d"
        lock_dir.mkdir(parents=True)
        an_hour_ago = time.time() - 3600
        os.utime(lock_dir, (an_hour_ago, an_hour_ago))
        uv_log = tmp_path / "uv_calls.log"
        stub_dir = _write_stub_uv(tmp_path, uv_log, sleep_seconds=0)
        env = _env(
            stub_dir,
            {"HOOKS_DAEMON_VENV_LOCK_BACKEND": "mkdir", "HOOKS_DAEMON_VENV_LOCK_TIMEOUT": "1"},
        )
        rc, out, err = _finish(_start(daemon_dir, env))
        assert rc == 0, err
        assert STALE_FRAGMENT in err, f"reclaiming a stale lock must be announced:\n{err}"
        assert len(_uv_calls(uv_log)) == 1
        assert (Path(out.strip()) / "bin" / "python").exists()
        assert not lock_dir.exists(), "the lock dir must be released after the build"

    def test_unknown_backend_is_rejected(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        uv_log = tmp_path / "uv_calls.log"
        stub_dir = _write_stub_uv(tmp_path, uv_log, sleep_seconds=0)
        env = _env(stub_dir, {"HOOKS_DAEMON_VENV_LOCK_BACKEND": "semaphore"})
        rc, _out, err = _finish(_start(daemon_dir, env))
        assert rc != 0
        assert "HOOKS_DAEMON_VENV_LOCK_BACKEND" in err, err
        assert _uv_calls(uv_log) == []


class TestFingerprintKeyedLockIsSharedAcrossStarters:
    """The lock is per daemon_dir, not per fingerprint: the ``rm -rf`` of a stale
    venv and the build of its replacement are one critical section."""

    def test_lock_file_sits_beside_the_venv(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        uv_log = tmp_path / "uv_calls.log"
        stub_dir = _write_stub_uv(tmp_path, uv_log, sleep_seconds=0)
        env = _env(stub_dir)
        rc, out, err = _finish(_start(daemon_dir, env))
        assert rc == 0, err
        fingerprint = _fingerprint(daemon_dir, env)
        assert Path(out.strip()) == daemon_dir / "untracked" / f"venv-{fingerprint}"
        assert (daemon_dir / "untracked" / LOCK_FILE_NAME).is_file()
