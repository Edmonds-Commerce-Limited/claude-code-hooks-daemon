"""`scripts/qa/acquire_full_qa_lock.bash` (Plan 00463 review 10 m1).

`run_tests.sh`'s own `flock "${FULL_QA_LOCK_FD}"` had no `-w` bound: a leaked
descriptor (review 10's H repro: a holder that backgrounds an orphan and
exits, `exec {FD}>>` without `FD_CLOEXEC`) left the NEXT run blocked forever
with no diagnostic. This module is now a small, separately sourceable bash
library so its locking behaviour can be proven without paying for a real
pytest/coverage run: a bounded wait (`flock -w`) that names the holding
pid(s) on timeout, taken from `run_tests.sh` verbatim.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCK_LIB = _REPO_ROOT / "scripts" / "qa" / "acquire_full_qa_lock.bash"
_PROBE_TIMEOUT_SECONDS = 15


def _run_acquire(lock_file: Path, *, wait_seconds: int) -> subprocess.CompletedProcess[str]:
    script = (
        "set -euo pipefail\n"
        f'source "{_LOCK_LIB}"\n'
        f"FULL_QA_LOCK_WAIT_SECONDS={wait_seconds}\n"
        f'acquire_full_qa_lock_or_die "{lock_file}"\n'
        "echo ACQUIRED\n"
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT_SECONDS,
        check=False,
    )


class TestUncontendedAcquireSucceeds:
    def test_acquires_immediately_when_nobody_holds_it(self, tmp_path: Path) -> None:
        lock_file = tmp_path / "lock"
        result = _run_acquire(lock_file, wait_seconds=5)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ACQUIRED" in result.stdout


class TestContendedAcquireGivesUpWithADiagnostic:
    def test_gives_up_after_the_bound_and_names_the_holder_pid(self, tmp_path: Path) -> None:
        """Review 10 m1: bounded wait, not an infinite `flock`. The bound
        itself is a subprocess.run `timeout=`, not a wall-clock assertion in
        the test body -- an unbounded `flock` would hang past it and this
        test would ERROR on TimeoutExpired, not merely fail an assertion."""
        lock_file = tmp_path / "lock"
        holder = subprocess.Popen(
            ["bash", "-c", f'exec 8>>"{lock_file}"; flock 8; echo held; sleep 30'],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert holder.stdout is not None
            assert holder.stdout.readline().strip() == "held"
            result = _run_acquire(lock_file, wait_seconds=1)
        finally:
            holder.kill()
            holder.wait(timeout=_PROBE_TIMEOUT_SECONDS)
        assert result.returncode == 1
        assert "ACQUIRED" not in result.stdout
        assert str(holder.pid) in result.stderr, f"stderr={result.stderr!r}"

    def test_the_holder_still_holds_it_afterwards(self, tmp_path: Path) -> None:
        """The failed waiter must not have grabbed the lock out from under
        the genuine holder (a probe run AFTER the waiter gives up finds it
        still exclusively locked)."""
        lock_file = tmp_path / "lock"
        holder = subprocess.Popen(
            ["bash", "-c", f'exec 8>>"{lock_file}"; flock 8; echo held; sleep 30'],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert holder.stdout is not None
            assert holder.stdout.readline().strip() == "held"
            _run_acquire(lock_file, wait_seconds=1)
            probe = subprocess.run(
                ["flock", "-n", str(lock_file), "true"],
                capture_output=True,
                timeout=_PROBE_TIMEOUT_SECONDS,
                check=False,
            )
        finally:
            holder.kill()
            holder.wait(timeout=_PROBE_TIMEOUT_SECONDS)
        assert probe.returncode == 1, "the lock must still be held by the original holder"


class TestAnInheritedHeldLockIsRecognised:
    """The matrix runner holds the lock and hands its fd to ``run_tests.sh``.

    A second, fresh ``flock`` on the same file would wait for the very process
    that launched it, so the library must recognise the inherited descriptor.
    Recognition is PROVEN by ``flock -n`` on that descriptor, never by the
    environment variable alone.
    """

    _SCRIPT = (
        "set -euo pipefail\n"
        f'source "{_LOCK_LIB}"\n'
        "FULL_QA_LOCK_WAIT_SECONDS=1\n"
        'acquire_full_qa_lock_or_die "$1"\n'
        "echo ACQUIRED\n"
    )

    @staticmethod
    def _open_locked(lock_file: Path) -> int:
        fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _acquire(
        self, lock_file: Path, fd: int, hint: str | None
    ) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k != "FULL_QA_LOCK_INHERITED_FD"}
        if hint is not None:
            env["FULL_QA_LOCK_INHERITED_FD"] = hint
        return subprocess.run(
            ["bash", "-c", self._SCRIPT, "bash", str(lock_file)],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
            pass_fds=(fd,),
            env=env,
        )

    def test_the_inherited_descriptor_that_holds_the_lock_is_accepted(self, tmp_path: Path) -> None:
        lock_file = tmp_path / "lock"
        fd = self._open_locked(lock_file)
        try:
            result = self._acquire(lock_file, fd, str(fd))
        finally:
            os.close(fd)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ACQUIRED" in result.stdout

    def test_without_the_hint_a_held_lock_is_still_contended(self, tmp_path: Path) -> None:
        lock_file = tmp_path / "lock"
        fd = self._open_locked(lock_file)
        try:
            result = self._acquire(lock_file, fd, None)
        finally:
            os.close(fd)
        assert result.returncode == 1
        assert "ACQUIRED" not in result.stdout

    def test_a_hint_naming_a_descriptor_on_another_file_proves_nothing(
        self, tmp_path: Path
    ) -> None:
        lock_file = tmp_path / "lock"
        holder = self._open_locked(lock_file)
        decoy = os.open(tmp_path / "other", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            result = self._acquire(lock_file, decoy, str(decoy))
        finally:
            os.close(decoy)
            os.close(holder)
        assert result.returncode == 1
        assert "ACQUIRED" not in result.stdout


class TestScriptIsExecutableAndShellchecked:
    def test_the_lock_library_exists_and_is_readable(self) -> None:
        assert _LOCK_LIB.is_file()

    def test_shellcheck_passes(self) -> None:
        shellcheck = subprocess.run(
            ["shellcheck", str(_LOCK_LIB)],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
        if shellcheck.returncode == 127:
            pytest.skip("shellcheck not installed on this machine")
        assert shellcheck.returncode == 0, shellcheck.stdout + shellcheck.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
