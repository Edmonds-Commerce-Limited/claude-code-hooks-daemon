"""The host-wide full-QA lock: the sink-side backstop (Plan 00463 round 9).

Review 9 found 81 of 202 evasion rows allowed because the guarantee lived only
in a Bash-text denylist: any program can start a whole-suite test run, so no
text pattern can enumerate every launcher. The fix moves the guarantee to the
SINK -- the pytest process itself refuses a whole-suite-sized run unless it
holds this lock, no matter what launched it.

"Holds the lock" must be PROVEN, not merely claimed. A child proves it by an
INHERITED file descriptor on the exact lock file (checked via /proc/self/fd),
confirmed by flock semantics (a probe on a fresh fd finds it exclusively
locked) -- never by an environment variable alone, which any evasion could set
for itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.qa.full_qa_lock import (
    acquire_full_qa_lock,
    full_qa_lock_is_held,
    git_common_dir,
    host_lock_path,
    open_lock_fd,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _init_repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """A tiny real repo plus a worktree of it, the shape this lock must span."""
    main = tmp_path / "main"
    main.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "HOME": str(tmp_path)}
    env["GIT_COMMITTER_NAME"] = "t"
    env["GIT_COMMITTER_EMAIL"] = "t@t"
    subprocess.run(["git", "init", "-q"], cwd=main, check=True, env=env)
    (main / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=main, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=main, check=True, env=env)
    subprocess.run(["git", "branch", "side"], cwd=main, check=True, env=env)
    worktree = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(worktree), "side"], cwd=main, check=True, env=env
    )
    return main, worktree


class TestHostLockPathSpansWorktrees:
    def test_main_checkout_and_its_worktree_resolve_the_same_lock_path(
        self, tmp_path: Path
    ) -> None:
        main, worktree = _init_repo_with_worktree(tmp_path)
        assert host_lock_path(main) == host_lock_path(worktree)

    def test_lock_path_lives_under_the_git_common_dir_not_the_worktree(
        self, tmp_path: Path
    ) -> None:
        _main, worktree = _init_repo_with_worktree(tmp_path)
        common = git_common_dir(worktree)
        assert host_lock_path(worktree).parent == common
        assert str(worktree) not in str(common)


class TestLockIsHeldIsProvenNotClaimed:
    def test_false_when_nobody_holds_it(self, tmp_path: Path) -> None:
        main, _ = _init_repo_with_worktree(tmp_path)
        assert full_qa_lock_is_held(main) is False

    def test_false_from_this_process_when_nothing_here_acquired_it(self, tmp_path: Path) -> None:
        """Merely resolving the path proves nothing -- it must be OPEN and LOCKED."""
        main, _ = _init_repo_with_worktree(tmp_path)
        host_lock_path(main).parent.mkdir(parents=True, exist_ok=True)
        host_lock_path(main).touch()
        assert full_qa_lock_is_held(main) is False

    def test_true_in_a_child_that_inherits_the_locked_fd(self, tmp_path: Path) -> None:
        """The fd `os.open` returns is non-inheritable by default (PEP 446),
        so a Python child must be handed it explicitly via `pass_fds` --
        `close_fds=False` alone does not survive `exec` for it. The prior
        version of this test asserted `"HELD" in probe.stdout`, which is also
        true of `"NOT-HELD"` and so passed without proving inheritance at
        all; tightened to an exact match."""
        main, _ = _init_repo_with_worktree(tmp_path)
        with acquire_full_qa_lock(main) as fd:
            os.set_inheritable(fd, True)
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.path.insert(0, sys.argv[1]); "
                    "from claude_code_hooks_daemon.qa.full_qa_lock import full_qa_lock_is_held; "
                    "from pathlib import Path; "
                    "print('HELD' if full_qa_lock_is_held(Path(sys.argv[2])) else 'NOT-HELD')",
                    str(PROJECT_ROOT / "src"),
                    str(main),
                ],
                pass_fds=(fd,),
                capture_output=True,
                text=True,
                timeout=Timeout.QA_TEST_TIMEOUT,
                check=False,
            )
        assert probe.stdout.strip() == "HELD", f"stdout={probe.stdout!r} stderr={probe.stderr!r}"

    def test_false_when_the_inherited_fd_itself_is_unlocked_even_if_another_holds_it(
        self, tmp_path: Path
    ) -> None:
        """Review 10 B2: an UNLOCKED fd to the lock path, while a SEPARATE process
        genuinely holds the lock, must not be believed -- the proof must be that
        THIS descriptor holds the lock, not merely that someone, somewhere, does.
        """
        main, _ = _init_repo_with_worktree(tmp_path)
        lock = host_lock_path(main)
        lock.parent.mkdir(parents=True, exist_ok=True)
        holder = subprocess.Popen(
            ["bash", "-c", f'exec 8>>"{lock}"; flock 8; echo held; sleep 30'],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert holder.stdout is not None
            assert holder.stdout.readline().strip() == "held"
            evader_fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o644)
            os.set_inheritable(evader_fd, True)
            try:
                probe = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import sys; sys.path.insert(0, sys.argv[1]); "
                        "from claude_code_hooks_daemon.qa.full_qa_lock import full_qa_lock_is_held; "
                        "from pathlib import Path; "
                        "print('HELD' if full_qa_lock_is_held(Path(sys.argv[2])) else 'NOT-HELD')",
                        str(PROJECT_ROOT / "src"),
                        str(main),
                    ],
                    pass_fds=(evader_fd,),
                    capture_output=True,
                    text=True,
                    timeout=Timeout.QA_TEST_TIMEOUT,
                    check=False,
                )
            finally:
                os.close(evader_fd)
        finally:
            holder.kill()
            holder.wait(timeout=Timeout.QA_TEST_TIMEOUT)
        assert "NOT-HELD" in probe.stdout, f"stdout={probe.stdout!r} stderr={probe.stderr!r}"

    def test_an_env_var_claim_with_no_real_inherited_fd_is_not_believed(
        self, tmp_path: Path
    ) -> None:
        """The fail-open this guards: spoofing possession without the fd."""
        main, _ = _init_repo_with_worktree(tmp_path)
        with acquire_full_qa_lock(main):
            pass  # released before the probe -- no fd, no lock, just a path.
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "from claude_code_hooks_daemon.qa.full_qa_lock import full_qa_lock_is_held; "
                "from pathlib import Path; "
                "print('HELD' if full_qa_lock_is_held(Path(sys.argv[2])) else 'NOT-HELD')",
                str(PROJECT_ROOT / "src"),
                str(main),
            ],
            env={**os.environ, "HOOKS_DAEMON_FULL_QA_LOCK_HELD": "1"},
            capture_output=True,
            text=True,
            timeout=Timeout.QA_TEST_TIMEOUT,
            check=False,
        )
        assert "NOT-HELD" in probe.stdout, f"stdout={probe.stdout!r} stderr={probe.stderr!r}"


class TestProvenFdIsMarkedCloexec:
    def test_the_fd_that_proved_possession_is_cloexec_afterwards(self, tmp_path: Path) -> None:
        """Review 10 m1: once a candidate fd has PROVEN it holds the lock,
        marking it CLOEXEC stops it leaking into further descendants THIS
        process forks (a test fixture that backgrounds an orphan process, the
        exact shape of review 10's H repro) -- it must still reach pytest
        itself via inheritance across `fork`/`exec`, so this only applies
        AFTER the proof, never before."""
        main, _ = _init_repo_with_worktree(tmp_path)
        script = (
            "import sys, os, fcntl; sys.path.insert(0, sys.argv[1])\n"
            "from claude_code_hooks_daemon.qa.full_qa_lock import (\n"
            "    full_qa_lock_is_held, host_lock_path,\n"
            ")\n"
            "from pathlib import Path\n"
            "root = Path(sys.argv[2])\n"
            "held = full_qa_lock_is_held(root)\n"
            "lock_path = host_lock_path(root).resolve()\n"
            "found = None\n"
            "for entry in os.listdir('/proc/self/fd'):\n"
            "    try:\n"
            "        target = Path(os.readlink(f'/proc/self/fd/{entry}'))\n"
            "    except OSError:\n"
            "        continue\n"
            "    if target != lock_path:\n"
            "        continue\n"
            "    flags = fcntl.fcntl(int(entry), fcntl.F_GETFD)\n"
            "    found = bool(flags & fcntl.FD_CLOEXEC)\n"
            "    break\n"
            "print('HELD' if held else 'NOT-HELD')\n"
            "print('CLOEXEC' if found else 'NOT-CLOEXEC')\n"
        )
        with acquire_full_qa_lock(main) as fd:
            os.set_inheritable(fd, True)
            probe = subprocess.run(
                [sys.executable, "-c", script, str(PROJECT_ROOT / "src"), str(main)],
                pass_fds=(fd,),
                capture_output=True,
                text=True,
                timeout=Timeout.QA_TEST_TIMEOUT,
                check=False,
            )
        assert (
            "HELD" in probe.stdout.splitlines()
        ), f"stdout={probe.stdout!r} stderr={probe.stderr!r}"
        assert (
            "CLOEXEC" in probe.stdout.splitlines()
        ), f"stdout={probe.stdout!r} stderr={probe.stderr!r}"


class TestSecondAcquisitionIsRefused:
    def test_nonblocking_second_acquire_is_refused_while_first_is_held(
        self, tmp_path: Path
    ) -> None:
        main, _ = _init_repo_with_worktree(tmp_path)
        probe = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from claude_code_hooks_daemon.qa.full_qa_lock import acquire_full_qa_lock; "
            "from pathlib import Path; "
            "import fcntl\n"
            "try:\n"
            "    with acquire_full_qa_lock(Path(sys.argv[2]), blocking=False):\n"
            "        print('ACQUIRED')\n"
            "except BlockingIOError:\n"
            "    print('REFUSED')\n"
        )
        with acquire_full_qa_lock(main):
            result = subprocess.run(
                [sys.executable, "-c", probe, str(PROJECT_ROOT / "src"), str(main)],
                capture_output=True,
                text=True,
                timeout=Timeout.QA_TEST_TIMEOUT,
                check=False,
            )
        assert "REFUSED" in result.stdout, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_lock_is_released_when_holder_exits(self, tmp_path: Path) -> None:
        main, _ = _init_repo_with_worktree(tmp_path)
        with acquire_full_qa_lock(main):
            pass
        fd = open_lock_fd(main)
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
