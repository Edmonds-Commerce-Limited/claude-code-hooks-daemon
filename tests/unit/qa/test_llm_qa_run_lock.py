"""The QA run lock must not outlive its run (Plan 00262 Phase 1, Plan 00463).

The lock is now the host-wide one in the common git dir (Plan 00475 Task 2.3;
see ``test_llm_qa_host_lock.py`` for the queueing, timeout and worktree tests).
What stays pinned here is a property of the descriptor itself:

The lock must not survive its holder. ``fcntl.flock`` is used rather than a
PID-file convention precisely because the kernel drops it when the process
dies -- including SIGKILL, which a PID file cannot handle. That removes the
entire stale-lock class rather than adding cleanup logic for it. And the run's
descriptor is opened non-inheritable, so a daemon a tool starts during the run
cannot keep the lock after the run exits.
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
        f"fd = m.acquire_host_lock({str(lock_path)!r}, wait_seconds=0, announce=print);"
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


class TestHolderStampIsTheContractTheDaemonReads:
    """``hooks-daemon restart`` warns from this stamp; the two must agree on its keys."""

    def test_stamp_records_the_holder_pid_and_checkout(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "qa.lock"
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT)
        try:
            llm_qa._stamp_holder(fd, Path("/some/checkout"))
        finally:
            os.close(fd)

        assert lock_path.read_text().splitlines() == [
            f"pid={os.getpid()}",
            "checkout=/some/checkout",
        ]

    def test_daemon_reads_the_stamp_the_runner_writes(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.daemon.cli import _recorded_qa_lock_holder

        lock_path = tmp_path / "qa.lock"
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT)
        try:
            llm_qa._stamp_holder(fd, tmp_path)
        finally:
            os.close(fd)

        assert _recorded_qa_lock_holder(lock_path, tmp_path) == str(os.getpid())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
