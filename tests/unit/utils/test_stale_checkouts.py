"""Tests for stale worktree and stale daemon detection (Plan 00470 Task 4.2).

Worktree detection runs real git over a temp repository; daemon detection is
driven by fake process tables and a fake liveness probe, so nothing here looks
at the host's real processes.
"""

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.worktree_reaping import MINIMUM_AGE_SECONDS
from claude_code_hooks_daemon.utils.stale_checkouts import (
    DaemonProcess,
    StaleDaemon,
    StaleWorktree,
    find_stale_daemons,
    find_stale_worktrees,
    registered_checkouts,
    render_stale_report,
)

_DAY = 86400.0
_OLD_ENOUGH = float(MINIMUM_AGE_SECONDS) + 1.0


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(cwd),
        },
    )
    return result.stdout


def _commit(cwd: Path, name: str) -> None:
    (cwd / name).write_text(name)
    _git(cwd, "add", name)
    _git(cwd, "commit", "-m", name)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _commit(root, "base.txt")
    return root


def _add_worktree(repo: Path, tmp_path: Path, branch: str) -> Path:
    path = tmp_path / f"wt-{branch}"
    _git(repo, "worktree", "add", "-b", branch, str(path))
    return path


def _old(_path: Path) -> float | None:
    return _OLD_ENOUGH


def _very_old(_path: Path) -> float | None:
    return 30 * _DAY


def _unknown_age(_path: Path) -> float | None:
    return None


def _too_young(_path: Path) -> float | None:
    return float(MINIMUM_AGE_SECONDS) - 1.0


def _no_processes() -> dict[int, Path]:
    return {}


class TestFindStaleWorktrees:
    def test_quiet_when_there_are_no_linked_worktrees(self, repo: Path) -> None:
        found = find_stale_worktrees(
            repo, "main", now=time.time(), age_fn=_old, process_cwds_fn=_no_processes
        )

        assert found == ()

    def test_branch_with_unmerged_work_is_not_stale(self, repo: Path, tmp_path: Path) -> None:
        wt = _add_worktree(repo, tmp_path, "work")
        _commit(wt, "new.txt")

        found = find_stale_worktrees(
            repo, "main", now=time.time(), age_fn=_old, process_cwds_fn=_no_processes
        )

        assert found == ()

    def test_fully_merged_branch_is_stale_with_cleanup_commands(
        self, repo: Path, tmp_path: Path
    ) -> None:
        wt = _add_worktree(repo, tmp_path, "done")
        _commit(wt, "new.txt")
        _git(repo, "merge", "--no-ff", "done", "-m", "merge done")

        found = find_stale_worktrees(
            repo, "main", now=time.time(), age_fn=_old, process_cwds_fn=_no_processes
        )

        assert len(found) == 1
        assert found[0].path == wt.resolve()
        assert found[0].branch == "done"
        assert any("merged into main" in reason for reason in found[0].reasons)
        assert found[0].commands == (f"git worktree remove {wt.resolve()}", "git branch -d done")

    def test_merged_branch_with_no_history_of_its_own_needs_minimum_age(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """A just-created worktree is an ancestor of main, exactly like a finished one."""
        _add_worktree(repo, tmp_path, "fresh")

        found = find_stale_worktrees(
            repo, "main", now=time.time(), age_fn=_too_young, process_cwds_fn=_no_processes
        )

        assert found == ()

    def test_unknown_age_is_never_read_as_old_enough(self, repo: Path, tmp_path: Path) -> None:
        _add_worktree(repo, tmp_path, "mystery")

        found = find_stale_worktrees(
            repo, "main", now=time.time(), age_fn=_unknown_age, process_cwds_fn=_no_processes
        )

        assert found == ()

    def test_live_process_inside_the_worktree_keeps_it_off_the_report(
        self, repo: Path, tmp_path: Path
    ) -> None:
        wt = _add_worktree(repo, tmp_path, "busy")

        found = find_stale_worktrees(
            repo,
            "main",
            now=time.time(),
            age_fn=_old,
            process_cwds_fn=lambda: {4242: wt.resolve() / "src"},
        )

        assert found == ()

    def test_missing_directory_is_prunable(self, repo: Path, tmp_path: Path) -> None:
        wt = _add_worktree(repo, tmp_path, "gone")
        _commit(wt, "x.txt")
        shutil.rmtree(wt)

        found = find_stale_worktrees(
            repo, "main", now=time.time(), age_fn=_old, process_cwds_fn=_no_processes
        )

        assert len(found) == 1
        assert any("directory is missing" in reason for reason in found[0].reasons)
        assert found[0].commands == ("git worktree prune",)

    def test_idle_branch_is_stale_after_the_configured_days(
        self, repo: Path, tmp_path: Path
    ) -> None:
        wt = _add_worktree(repo, tmp_path, "slow")
        _commit(wt, "x.txt")

        found = find_stale_worktrees(
            repo,
            "main",
            max_idle_days=7,
            now=time.time() + 8 * _DAY,
            age_fn=_very_old,
            process_cwds_fn=_no_processes,
        )

        assert len(found) == 1
        assert any("no commit for 8 days" in reason for reason in found[0].reasons)

    def test_idle_branch_inside_the_window_is_not_stale(self, repo: Path, tmp_path: Path) -> None:
        wt = _add_worktree(repo, tmp_path, "recent")
        _commit(wt, "x.txt")

        found = find_stale_worktrees(
            repo,
            "main",
            max_idle_days=7,
            now=time.time() + 3 * _DAY,
            age_fn=_very_old,
            process_cwds_fn=_no_processes,
        )

        assert found == ()

    def test_idle_needs_the_worktree_itself_to_be_that_old(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """A worktree cut an hour ago from an old commit has not been idle for days."""
        wt = _add_worktree(repo, tmp_path, "newcut")
        _commit(wt, "x.txt")

        found = find_stale_worktrees(
            repo,
            "main",
            max_idle_days=7,
            now=time.time() + 30 * _DAY,
            age_fn=_old,
            process_cwds_fn=_no_processes,
        )

        assert found == ()

    def test_locked_worktree_is_a_deliberate_hold(self, repo: Path, tmp_path: Path) -> None:
        wt = _add_worktree(repo, tmp_path, "held")
        _git(repo, "worktree", "lock", str(wt))

        found = find_stale_worktrees(
            repo, "main", now=time.time(), age_fn=_old, process_cwds_fn=_no_processes
        )

        assert found == ()

    def test_unreadable_listing_reports_nothing(self, tmp_path: Path) -> None:
        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()

        assert find_stale_worktrees(not_a_repo, "main") == ()

    def test_never_modifies_anything(self, repo: Path, tmp_path: Path) -> None:
        wt = _add_worktree(repo, tmp_path, "done")
        before = _git(repo, "worktree", "list", "--porcelain")

        find_stale_worktrees(
            repo, "main", now=time.time(), age_fn=_old, process_cwds_fn=_no_processes
        )

        assert _git(repo, "worktree", "list", "--porcelain") == before
        assert wt.is_dir()
        assert "done" in _git(repo, "branch", "--list")


class TestRegisteredCheckouts:
    def test_lists_main_and_linked_worktrees(self, repo: Path, tmp_path: Path) -> None:
        wt = _add_worktree(repo, tmp_path, "one")

        roots = registered_checkouts(repo)

        assert roots[0] == repo.resolve()
        assert wt.resolve() in roots

    def test_unreadable_listing_is_empty(self, tmp_path: Path) -> None:
        assert registered_checkouts(tmp_path) == ()


def _pid_file(directory: Path, text: str, name: str = "daemon.pid") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text)
    return path


def _untracked(root: Path) -> Path:
    return root / "untracked"


def _alive(_pid: int) -> bool:
    return True


def _dead(_pid: int) -> bool:
    return False


def _no_daemons() -> tuple[DaemonProcess, ...]:
    return ()


class TestFindStaleDaemons:
    def test_quiet_when_everything_is_alive_and_rooted(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        _pid_file(_untracked(root), "4242\n")

        found = find_stale_daemons(
            (root,),
            processes_fn=lambda: (DaemonProcess(pid=4242, root=str(root)),),
            pid_alive_fn=_alive,
            untracked_dir_fn=_untracked,
        )

        assert found == ()

    def test_pid_file_with_dead_pid_is_stale(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        pid_file = _pid_file(_untracked(root), "4242\n")

        found = find_stale_daemons(
            (root,),
            processes_fn=_no_daemons,
            pid_alive_fn=_dead,
            untracked_dir_fn=_untracked,
        )

        assert len(found) == 1
        assert found[0].subject == str(pid_file)
        assert "pid 4242 is not running" in found[0].reason
        assert found[0].commands == (f"bin/hooks-daemon --project-root {root} stop",)

    def test_corrupt_pid_file_is_stale(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        _pid_file(_untracked(root), "not-a-pid")

        found = find_stale_daemons(
            (root,),
            processes_fn=_no_daemons,
            pid_alive_fn=_alive,
            untracked_dir_fn=_untracked,
        )

        assert len(found) == 1
        assert "corrupt" in found[0].reason

    def test_host_suffixed_pid_files_are_read_too(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        _pid_file(_untracked(root), "4242\n", name="daemon-box.pid")

        found = find_stale_daemons(
            (root,),
            processes_fn=_no_daemons,
            pid_alive_fn=_dead,
            untracked_dir_fn=_untracked,
        )

        assert len(found) == 1

    def test_checkout_without_untracked_dir_is_skipped(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        root.mkdir()

        found = find_stale_daemons(
            (root,),
            processes_fn=_no_daemons,
            pid_alive_fn=_dead,
            untracked_dir_fn=_untracked,
        )

        assert found == ()

    def test_daemon_process_whose_root_no_longer_exists_is_stale(self, tmp_path: Path) -> None:
        gone = tmp_path / "deleted-worktree"

        found = find_stale_daemons(
            (),
            processes_fn=lambda: (DaemonProcess(pid=777, root=str(gone)),),
            pid_alive_fn=_alive,
            untracked_dir_fn=_untracked,
        )

        assert len(found) == 1
        assert found[0].subject == "daemon pid 777"
        assert str(gone) in found[0].reason
        assert found[0].commands == ("kill 777",)

    def test_daemon_process_with_unknown_root_is_left_alone(self) -> None:
        """A daemon this check cannot attribute is never reported."""
        found = find_stale_daemons(
            (),
            processes_fn=lambda: (DaemonProcess(pid=777, root=None),),
            pid_alive_fn=_alive,
            untracked_dir_fn=_untracked,
        )

        assert found == ()

    def test_daemon_process_with_existing_root_is_not_stale(self, tmp_path: Path) -> None:
        found = find_stale_daemons(
            (),
            processes_fn=lambda: (DaemonProcess(pid=777, root=str(tmp_path)),),
            pid_alive_fn=_alive,
            untracked_dir_fn=_untracked,
        )

        assert found == ()


class TestRenderStaleReport:
    def test_none_when_nothing_is_stale(self) -> None:
        assert render_stale_report((), ()) is None

    def test_names_each_finding_and_its_cleanup_command(self) -> None:
        worktree = StaleWorktree(
            path=Path("/w/a"),
            branch="a",
            reasons=("branch fully merged into main",),
            commands=("git worktree remove /w/a", "git branch -d a"),
        )
        daemon = StaleDaemon(
            subject="daemon pid 9",
            reason="project root /gone no longer exists",
            commands=("kill 9",),
        )

        report = render_stale_report((worktree,), (daemon,))

        assert report is not None
        assert "/w/a" in report
        assert "branch fully merged into main" in report
        assert "git worktree remove /w/a" in report
        assert "git branch -d a" in report
        assert "daemon pid 9" in report
        assert "kill 9" in report
        assert "does not run" in report

    def test_worktree_heading_absent_when_only_daemons_are_stale(self) -> None:
        daemon = StaleDaemon(subject="s", reason="r", commands=("kill 1",))

        report = render_stale_report((), (daemon,))

        assert report is not None
        assert "Stale worktrees" not in report
        assert "Stale daemons" in report
