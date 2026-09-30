"""Every ``llm_qa.py`` run that executes tools takes ONE host-wide lock (Plan 00475 Task 2.3).

Owner rule: never more than one QA process at once on the host. The old
per-checkout ``flock`` on ``untracked/qa/.llm_qa.lock`` could not stop runs in
DIFFERENT worktrees, and refused a second run in the SAME checkout instead of
queueing it. The lock is now the file whole-suite pytest already uses,
``<git-common-dir>/hooksdaemon-full-qa.lock``, so a tool run holds the very lock
the conftest sink and ``run_tests.sh`` recognise -- with a bounded wait that
queues, says who it is waiting on, and times out with its own exit code.

``llm_qa.py`` runs under the system ``python3`` before any venv, so it cannot
import ``claude_code_hooks_daemon.qa.full_qa_lock``. It re-implements the same
lock over the same file; the drift guard below pins that the two agree.
"""

from __future__ import annotations

import fcntl
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.qa.full_qa_lock import (
    acquire_full_qa_lock,
    full_qa_lock_is_held,
)
from claude_code_hooks_daemon.qa.full_qa_lock import host_lock_path as package_host_lock_path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LLM_QA_PATH = PROJECT_ROOT / "scripts" / "qa" / "llm_qa.py"


def _load_llm_qa() -> Any:
    """Import ``scripts/qa/llm_qa.py``, which is a script rather than a module."""
    spec = importlib.util.spec_from_file_location("llm_qa_host_lock_under_test", LLM_QA_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {LLM_QA_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load_llm_qa()

_GIT_ENV_KEYS = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(cwd: Path, *args: str) -> None:
    env = {**os.environ, **_GIT_ENV_KEYS, "HOME": str(cwd.parent)}
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        env=env,
        capture_output=True,
        timeout=Timeout.QA_TEST_TIMEOUT,
    )


@pytest.fixture
def worktrees(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A throwaway repo and TWO linked worktrees of it: (main, one, two)."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    (main / "f.txt").write_text("x")
    _git(main, "add", "f.txt")
    _git(main, "commit", "-q", "-m", "x")
    linked: list[Path] = []
    for name in ("one", "two"):
        path = tmp_path / name
        _git(main, "worktree", "add", "-q", "-b", name, str(path))
        linked.append(path)
    return main, linked[0], linked[1]


def _hold_in_process(path: Path) -> int:
    """Take the lock on a descriptor of this process, as another run would."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


class TestLockIsTheOneSharedFile:
    """Drift guard: the stdlib copy and the package agree on the lock file."""

    def test_every_worktree_resolves_the_package_lock_path(
        self, worktrees: tuple[Path, Path, Path]
    ) -> None:
        main, one, two = worktrees
        expected = package_host_lock_path(main)

        assert llm_qa.host_lock_path(main) == expected
        assert llm_qa.host_lock_path(one) == expected
        assert llm_qa.host_lock_path(two) == expected

    def test_lock_file_name_matches_the_package_constant(self) -> None:
        from claude_code_hooks_daemon.qa.full_qa_lock import LOCK_FILE_NAME

        assert llm_qa.HOST_LOCK_NAME == LOCK_FILE_NAME

    def test_outside_a_git_repository_is_a_clear_error(self, tmp_path: Path) -> None:
        with pytest.raises(OSError, match="git-common-dir"):
            llm_qa.host_lock_path(tmp_path)


class TestBoundedWait:
    """The wait queues, announces, and gives up with a distinct outcome."""

    def test_free_lock_is_taken_without_announcing(self, tmp_path: Path) -> None:
        messages: list[str] = []

        fd = llm_qa.acquire_host_lock(
            tmp_path / "qa.lock", wait_seconds=5, announce=messages.append
        )
        os.close(fd)

        assert messages == []

    def test_held_lock_is_waited_for_and_taken_when_released(self, tmp_path: Path) -> None:
        lock = tmp_path / "qa.lock"
        holder = _hold_in_process(lock)
        messages: list[str] = []
        sleeps: list[float] = []

        def release_after_first_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            os.close(holder)

        fd = llm_qa.acquire_host_lock(
            lock, wait_seconds=60, announce=messages.append, sleep=release_after_first_sleep
        )
        os.close(fd)

        assert len(sleeps) == 1
        assert len(messages) == 1
        assert "waiting" in messages[0].lower()

    def test_timeout_raises_naming_the_holder_and_the_bound(self, tmp_path: Path) -> None:
        lock = tmp_path / "qa.lock"
        holder = _hold_in_process(lock)
        llm_qa._stamp_holder(holder, Path("/some/checkout"))
        now = [0.0]

        def advance(seconds: float) -> None:
            now[0] += seconds

        try:
            with pytest.raises(llm_qa.LockTimeout) as excinfo:
                llm_qa.acquire_host_lock(
                    lock,
                    wait_seconds=10,
                    announce=lambda _message: None,
                    clock=lambda: now[0],
                    sleep=advance,
                )
        finally:
            os.close(holder)

        message = str(excinfo.value)
        assert str(os.getpid()) in message
        assert "/some/checkout" in message
        assert "10" in message

    def test_a_dead_recorded_holder_is_not_named(self, tmp_path: Path) -> None:
        """The stamp survives its writer; a stale pid must not be reported as live."""
        lock = tmp_path / "qa.lock"
        holder = _hold_in_process(lock)
        lock.write_text("pid=999999999\ncheckout=/gone\n")

        description = llm_qa.describe_holder(lock)
        os.close(holder)

        assert "999999999" not in description
        assert "/gone" not in description

    def test_wait_seconds_comes_from_the_shared_environment_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FULL_QA_LOCK_WAIT_SECONDS", "42")
        assert llm_qa.configured_wait_seconds() == 42

    def test_wait_seconds_defaults_to_the_bash_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FULL_QA_LOCK_WAIT_SECONDS", raising=False)
        assert llm_qa.configured_wait_seconds() == 600

    @pytest.mark.parametrize("bad", ["soon", "-1", ""])
    def test_a_bad_wait_seconds_fails_fast(self, monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
        monkeypatch.setenv("FULL_QA_LOCK_WAIT_SECONDS", bad)
        with pytest.raises(ValueError, match="FULL_QA_LOCK_WAIT_SECONDS"):
            llm_qa.configured_wait_seconds()

    def test_timeout_exit_code_is_distinct_from_every_other(self) -> None:
        codes = {
            llm_qa.EXIT_SUCCESS,
            llm_qa.EXIT_FAILURE,
            llm_qa.EXIT_LOCK_TIMEOUT,
        }
        assert len(codes) == 3
        assert llm_qa.EXIT_LOCK_TIMEOUT not in (2, 3)


class TestMainTakesTheLockOnlyWhenItExecutesTools:
    @pytest.fixture
    def patched_main(
        self,
        monkeypatch: pytest.MonkeyPatch,
        worktrees: tuple[Path, Path, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> list[dict[str, Any]]:
        """``main()`` rooted in a throwaway worktree with the tool loop recorded."""
        _main, one, _two = worktrees
        calls: list[dict[str, Any]] = []

        def fake_run_tools(tools: list[str], **kwargs: Any) -> int:
            calls.append({"tools": tools, **kwargs})
            return llm_qa.EXIT_SUCCESS

        monkeypatch.setattr(llm_qa, "PROJECT_ROOT", one)
        monkeypatch.setattr(llm_qa, "venv_python", lambda: Path(sys.executable))
        monkeypatch.setattr(llm_qa, "_run_tools", fake_run_tools)
        monkeypatch.setenv("FULL_QA_LOCK_WAIT_SECONDS", "0")
        return calls

    def _run(self, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
        monkeypatch.setattr(sys, "argv", ["llm_qa.py", *argv])
        result: int = llm_qa.main()
        return result

    def test_executing_run_holds_the_lock_while_tools_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_main: list[dict[str, Any]],
        worktrees: tuple[Path, Path, Path],
    ) -> None:
        _main, _one, two = worktrees
        observed: list[bool] = []

        def probe(tools: list[str], **kwargs: Any) -> int:
            fd = os.open(llm_qa.host_lock_path(two), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                observed.append(True)
            else:
                observed.append(False)
            finally:
                os.close(fd)
            assert isinstance(kwargs.get("lock_fd"), int)
            return llm_qa.EXIT_SUCCESS

        monkeypatch.setattr(llm_qa, "_run_tools", probe)

        assert self._run(monkeypatch, "format") == llm_qa.EXIT_SUCCESS
        assert observed == [True]

    def test_lock_is_released_when_the_run_ends(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_main: list[dict[str, Any]],
        worktrees: tuple[Path, Path, Path],
    ) -> None:
        _main, _one, two = worktrees

        assert self._run(monkeypatch, "format") == llm_qa.EXIT_SUCCESS

        fd = _hold_in_process(llm_qa.host_lock_path(two))
        os.close(fd)

    def test_busy_host_times_out_with_the_distinct_exit_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_main: list[dict[str, Any]],
        worktrees: tuple[Path, Path, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _main, _one, two = worktrees
        holder = _hold_in_process(llm_qa.host_lock_path(two))
        llm_qa._stamp_holder(holder, two)
        try:
            code = self._run(monkeypatch, "format")
        finally:
            os.close(holder)

        assert code == llm_qa.EXIT_LOCK_TIMEOUT
        assert patched_main == []
        stderr = capsys.readouterr().err
        assert str(os.getpid()) in stderr
        assert str(two) in stderr
        assert "FULL_QA_LOCK_WAIT_SECONDS" in stderr

    @pytest.mark.parametrize(
        "argv",
        [
            ("--read-only", "format"),
            ("--help",),
            ("main-moved",),
        ],
        ids=["read-only", "help", "main-moved"],
    )
    def test_commands_that_run_no_tools_never_wait(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patched_main: list[dict[str, Any]],
        worktrees: tuple[Path, Path, Path],
        argv: tuple[str, ...],
    ) -> None:
        _main, _one, two = worktrees
        holder = _hold_in_process(llm_qa.host_lock_path(two))
        try:
            code = self._run(monkeypatch, *argv)
        finally:
            os.close(holder)

        assert code != llm_qa.EXIT_LOCK_TIMEOUT


_HOLDER_DRIVER = """
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("m", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
fd = m.acquire_host_lock(m.host_lock_path(Path(sys.argv[2])), wait_seconds=5,
                         announce=lambda message: None)
m._stamp_holder(fd, Path(sys.argv[2]))
print("HELD", flush=True)
sys.stdin.readline()
"""

_WAITER_DRIVER = """
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("m", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
fd = m.acquire_host_lock(m.host_lock_path(Path(sys.argv[2])), wait_seconds=30,
                         announce=lambda message: print(message, file=sys.stderr, flush=True))
print("ACQUIRED", flush=True)
"""

_RUN_DRIVER = """
import importlib.util, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("m", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
root, log = Path(sys.argv[2]), Path(sys.argv[3])
m.PROJECT_ROOT = root
m.venv_python = lambda: Path(sys.executable)

def timed_tools(tools, **kwargs):
    with log.open("a") as handle:
        handle.write(f"start {time.monotonic()}\\n")
    time.sleep(0.8)
    with log.open("a") as handle:
        handle.write(f"end {time.monotonic()}\\n")
    return 0

m._run_tools = timed_tools
sys.argv = ["llm_qa.py", "format"]
sys.exit(m.main())
"""


class TestTwoLinkedWorktreesSerialise:
    """The whole point: runs in DIFFERENT checkouts queue instead of overlapping."""

    def test_second_worktree_queues_behind_the_first_and_names_it(
        self, worktrees: tuple[Path, Path, Path]
    ) -> None:
        _main, one, two = worktrees
        holder = subprocess.Popen(
            [sys.executable, "-c", _HOLDER_DRIVER, str(LLM_QA_PATH), str(one)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        waiter: subprocess.Popen[str] | None = None
        try:
            assert holder.stdout is not None and holder.stdin is not None
            assert holder.stdout.readline().strip() == "HELD"
            waiter = subprocess.Popen(
                [sys.executable, "-c", _WAITER_DRIVER, str(LLM_QA_PATH), str(two)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert waiter.stderr is not None and waiter.stdout is not None
            notice = waiter.stderr.readline()
            assert waiter.poll() is None, "the second run must be queued, not finished"
            assert str(holder.pid) in notice
            assert str(one) in notice

            holder.stdin.write("release\n")
            holder.stdin.flush()
            assert waiter.wait(timeout=Timeout.QA_TEST_TIMEOUT) == 0
            assert waiter.stdout.read().strip() == "ACQUIRED"
        finally:
            for process in (holder, waiter):
                if process is not None and process.poll() is None:
                    process.kill()
                if process is not None:
                    process.wait(timeout=Timeout.QA_TEST_TIMEOUT)
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()

    def test_two_full_main_runs_never_overlap(self, worktrees: tuple[Path, Path, Path]) -> None:
        _main, one, two = worktrees
        log = one.parent / "runs.log"
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", _RUN_DRIVER, str(LLM_QA_PATH), str(root), str(log)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            for root in (one, two)
        ]
        for process in processes:
            _stdout, stderr = process.communicate(timeout=Timeout.QA_TEST_TIMEOUT)
            assert process.returncode == 0, stderr

        events = [line.split() for line in log.read_text().splitlines()]
        assert [kind for kind, _ in events] == ["start", "end", "start", "end"]
        first_end = float(events[1][1])
        second_start = float(events[2][1])
        assert second_start >= first_end


_PROBE_TOOL = """
import os, sys
from pathlib import Path
from claude_code_hooks_daemon.qa.full_qa_lock import acquire_full_qa_lock, full_qa_lock_is_held
root, out = Path(sys.argv[1]), Path(sys.argv[2])
held = full_qa_lock_is_held(root)
try:
    with acquire_full_qa_lock(root, blocking=False, reuse_inherited=True):
        reentered = True
except BlockingIOError:
    reentered = False
out.write_text(f"{held} {reentered} {os.environ.get('FULL_QA_LOCK_INHERITED_FD', '')}")
"""


class TestWholeSuiteInsideARunDoesNotDeadlock:
    """A tool the run starts must accept the lock its parent already holds."""

    def _run_probe(
        self, monkeypatch: pytest.MonkeyPatch, root: Path, *, lock_fd: int | None
    ) -> list[str]:
        out = root.parent / "probe.txt"
        out.unlink(missing_ok=True)
        config = llm_qa.ToolConfig(
            command=[sys.executable, "-c", _PROBE_TOOL, str(root), str(out)],
            json_file="probe.json",
            jq_hint="",
        )
        monkeypatch.setitem(llm_qa.TOOL_REGISTRY, "probe", config)
        code = llm_qa.run_tool("probe", lock_fd=lock_fd)
        assert code == 0
        return out.read_text().split()

    def test_child_of_a_holding_run_proves_possession_and_reenters(
        self, monkeypatch: pytest.MonkeyPatch, worktrees: tuple[Path, Path, Path]
    ) -> None:
        _main, one, _two = worktrees
        fd = llm_qa.acquire_host_lock(
            llm_qa.host_lock_path(one), wait_seconds=5, announce=lambda _m: None
        )
        try:
            held, reentered, hint = self._run_probe(monkeypatch, one, lock_fd=fd)
        finally:
            os.close(fd)

        assert held == "True"
        assert reentered == "True"
        assert hint == str(fd)

    def test_control_child_of_a_run_that_passed_nothing_is_locked_out(
        self, monkeypatch: pytest.MonkeyPatch, worktrees: tuple[Path, Path, Path]
    ) -> None:
        _main, one, _two = worktrees
        fd = llm_qa.acquire_host_lock(
            llm_qa.host_lock_path(one), wait_seconds=5, announce=lambda _m: None
        )
        try:
            held, reentered, *_hint = self._run_probe(monkeypatch, one, lock_fd=None)
        finally:
            os.close(fd)

        assert held == "False"
        assert reentered == "False"


class TestReuseInheritedOnThePackageLock:
    def test_default_acquire_still_contends_with_a_held_descriptor(
        self, worktrees: tuple[Path, Path, Path]
    ) -> None:
        """Re-entry is opt-in: a plain acquire must keep refusing a second holder."""
        main, _one, _two = worktrees
        with acquire_full_qa_lock(main):
            with pytest.raises(BlockingIOError):
                with acquire_full_qa_lock(main, blocking=False):
                    pass

    def test_reuse_yields_the_held_descriptor_and_leaves_it_open(
        self, worktrees: tuple[Path, Path, Path]
    ) -> None:
        main, _one, _two = worktrees
        with acquire_full_qa_lock(main) as outer:
            with acquire_full_qa_lock(main, blocking=False, reuse_inherited=True) as inner:
                assert inner == outer
            assert full_qa_lock_is_held(main)
            os.fstat(outer)

    def test_reuse_falls_back_to_a_fresh_acquire_when_nothing_is_inherited(
        self, worktrees: tuple[Path, Path, Path]
    ) -> None:
        main, _one, _two = worktrees
        with acquire_full_qa_lock(main, reuse_inherited=True) as fd:
            assert full_qa_lock_is_held(main)
        with pytest.raises(OSError):
            os.fstat(fd)
