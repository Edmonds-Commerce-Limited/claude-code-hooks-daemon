"""A second QA run must not silently race a first (Plan 00262 Phase 1).

Nothing stopped a second `llm_qa.py` starting while one was already in flight.
Both drive the same `tests/` tree and both write `untracked/qa/coverage.json`,
so the two contend and NEITHER verdict can be trusted -- a contended run can
fail a check that is fine, and pass one that is not.

That matters because this is a GATING signal: `CLAUDE.md` and `RELEASING.md`
both make a green QA run a precondition for committing and for releasing. A
guard whose verdict is unreliable under a condition nobody detects converts a
blocking gate into a coin flip without saying so.

Found by causing it: two suites raced for ~7 minutes during Plan 00261, and
earlier in that same session a `test_install_sh_end_to_end` failure from the
same cause was dismissed as a one-off. That is the real damage -- a contended
run teaches you to discount failures.

TWO DESIGN POINTS PINNED HERE:

`--read-only` must stay unlocked. It never runs tools (the executing loop in
`main()` is guarded by `if not read_only`), so it cannot contend -- and it is
exactly the command someone would reach for to inspect a run already in
progress. Locking it would block the diagnostic during the only situation where
the diagnostic is wanted.

The lock must not survive its holder. `fcntl.flock` is used rather than a
PID-file convention precisely because the kernel drops it when the process
dies -- including SIGKILL, which a PID file cannot handle. That removes the
entire stale-lock class rather than adding cleanup logic for it.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_llm_qa() -> Any:
    """Import `scripts/qa/llm_qa.py`, which is a script rather than a module."""
    module_path = PROJECT_ROOT / "scripts" / "qa" / "llm_qa.py"
    spec = importlib.util.spec_from_file_location("llm_qa_lock_under_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load_llm_qa()


class TestRunLockExists:
    """The lock primitive itself."""

    def test_module_exposes_a_run_lock(self) -> None:
        assert hasattr(llm_qa, "run_lock"), "llm_qa must expose a run_lock context manager"

    def test_lock_path_is_not_in_tmp(self, tmp_path: Path) -> None:
        """Security standard B108: never `/tmp` for runtime files.

        The daemon's own rule is that runtime state lives under the project's
        untracked dir, not a world-writable shared directory.
        """
        lock_path = llm_qa.run_lock_path()
        assert not str(lock_path).startswith("/tmp/"), f"lock must not live in /tmp: {lock_path}"
        assert "untracked" in str(lock_path), f"lock should live under untracked/: {lock_path}"


class TestSecondRunIsRefused:
    """The behaviour that matters: two runs cannot execute tools concurrently."""

    def test_second_acquisition_is_refused_while_first_is_held(self, tmp_path: Path) -> None:
        """The core guarantee. Held in-process, contended from a child.

        A same-process second acquire would prove nothing: `flock` is advisory
        per open-file-description, so the honest test needs a real second
        process -- which is also the shape of the real failure.
        """
        lock_path = tmp_path / "qa.lock"

        probe = (
            "import sys;"
            f"sys.path.insert(0, {str(PROJECT_ROOT / 'scripts' / 'qa')!r});"
            "import importlib.util;"
            f"spec = importlib.util.spec_from_file_location('m', {str(PROJECT_ROOT / 'scripts' / 'qa' / 'llm_qa.py')!r});"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
            f"acquired = m.try_acquire_run_lock({str(lock_path)!r});"
            "print('ACQUIRED' if acquired else 'REFUSED')"
        )

        with llm_qa.run_lock(lock_path):
            result = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True,
                text=True,
                timeout=Timeout.QA_TEST_TIMEOUT,
                check=False,
            )

        assert "REFUSED" in result.stdout, (
            "a second process must be refused while the lock is held. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_lock_is_released_when_holder_exits(self, tmp_path: Path) -> None:
        """After the holder releases, the next run must proceed.

        A guard that permanently wedges the suite would be worse than the race
        it prevents -- an agent would learn to delete the lock file, which
        reintroduces the race AND removes the signal.
        """
        lock_path = tmp_path / "qa.lock"

        with llm_qa.run_lock(lock_path):
            pass

        assert llm_qa.try_acquire_run_lock(str(lock_path)) is True


def _run_that_starts_a_daemon(lock_path: Path, *, leak_the_lock: bool) -> tuple[int, int]:
    """A QA run that takes the lock, starts a long-lived child, and exits.

    The child is started the way a daemon restart starts one: its own session,
    and ``close_fds=False``, so it inherits every descriptor that CAN be
    inherited. ``leak_the_lock`` marks the lock descriptor inheritable, the
    shape of the defect, so the probe is shown able to see a leak.

    The child lives until the returned write end of a pipe is closed: it
    blocks reading the pipe, so the test ends it by closing a descriptor it
    owns rather than by signalling a pid it does not own.

    Returns:
        The pid of the child, still running after the run has exited, and the
        write end of the pipe that keeps it alive.
    """
    read_end, write_end = os.pipe()
    script = (
        "import os, subprocess, sys, importlib.util;"
        f"spec = importlib.util.spec_from_file_location('m', {str(PROJECT_ROOT / 'scripts' / 'qa' / 'llm_qa.py')!r});"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
        f"fd = m._open_lock_fd({str(lock_path)!r});"
        "import fcntl; fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB);"
        f"os.set_inheritable(fd, {leak_the_lock!r});"
        f"child = subprocess.Popen([sys.executable, '-c', 'import os; os.read({read_end}, 1)'],"
        " close_fds=False, start_new_session=True,"
        " stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL);"
        "print(child.pid)"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=Timeout.QA_TEST_TIMEOUT,
            check=True,
            pass_fds=(read_end,),
        )
    except BaseException:
        os.close(write_end)
        raise
    finally:
        os.close(read_end)
    return int(result.stdout.strip()), write_end


class TestADaemonStartedUnderTheRunDoesNotHoldTheLock:
    """Plan 00463 lock-fd finding: a lock held across a command that daemonises.

    The coordinator's serial gate held an ``flock`` around ``hooks-daemon
    restart`` plus ``llm_qa.py all``. The restarted daemon inherited the lock's
    descriptor, outlived the gate, and held the lock, so the next gate waited
    forever. ``llm_qa.py``'s own run lock is opened with ``os.open``, which is
    non-inheritable (PEP 446), so a daemon a tool starts during the run cannot
    keep it. Pinned end to end, with a control that shows the probe sees a leak.
    """

    @pytest.mark.parametrize(
        ("leak_the_lock", "released"), [(False, True), (True, False)], ids=["real", "control"]
    )
    def test_the_lock_is_released_when_the_run_exits_while_its_child_lives_on(
        self, tmp_path: Path, leak_the_lock: bool, released: bool
    ) -> None:
        lock_path = tmp_path / "qa.lock"
        child, keep_alive = _run_that_starts_a_daemon(lock_path, leak_the_lock=leak_the_lock)
        try:
            os.kill(child, 0)
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import fcntl, os;"
                    f"fd = os.open({str(lock_path)!r}, os.O_RDWR);"
                    "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)",
                ],
                capture_output=True,
                timeout=Timeout.QA_TEST_TIMEOUT,
                check=False,
            )
            assert (probe.returncode == 0) is released, probe.stderr
        finally:
            os.close(keep_alive)


class TestHolderIsIdentified:
    """A refusal must be actionable, not merely a refusal."""

    def test_lock_file_records_the_holder_pid(self, tmp_path: Path) -> None:
        """'Already running' with no detail invites deleting the lock file.

        Naming the PID lets the reader check whether it is alive, and decide
        between waiting and investigating.
        """
        lock_path = tmp_path / "qa.lock"

        with llm_qa.run_lock(lock_path):
            recorded = lock_path.read_text()

        assert (
            str(os.getpid()) in recorded
        ), f"lock file must record the holder pid, got {recorded!r}"

    def test_refusal_message_names_the_pid_and_what_to_do(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "qa.lock"

        with llm_qa.run_lock(lock_path):
            message = llm_qa.busy_message(str(lock_path))

        assert str(os.getpid()) in message, "refusal must name the live run's pid"
        assert "--read-only" in message, "refusal should point at the read-only inspection route"


class TestReadOnlyIsNotLocked:
    """`--read-only` runs no tools, so it must never be blocked."""

    def test_read_only_run_succeeds_while_lock_is_held(self, tmp_path: Path) -> None:
        """The diagnostic must work during the only situation it is wanted in."""
        lock_path = tmp_path / "qa.lock"

        with llm_qa.run_lock(lock_path):
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "qa" / "llm_qa.py"),
                    "--read-only",
                    "format",
                ],
                capture_output=True,
                text=True,
                timeout=Timeout.QA_TEST_TIMEOUT,
                check=False,
                cwd=str(PROJECT_ROOT),
            )

        assert (
            "already running" not in result.stdout.lower()
        ), f"--read-only must not be refused by the run lock. stdout={result.stdout!r}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
