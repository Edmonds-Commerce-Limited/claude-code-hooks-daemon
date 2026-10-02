"""Tests for stale worktree and stale daemon detection (Plan 00470 Task 4.2).

Worktree detection runs real git over a temp repository; daemon detection is
driven by fake process tables and a fake liveness probe, so nothing here looks
at the host's real processes.
"""

import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.worktree_reaping import MINIMUM_AGE_SECONDS
from claude_code_hooks_daemon.daemon.paths import get_pid_path, pid_file_name
from claude_code_hooks_daemon.daemon.process_verification import RootProof
from claude_code_hooks_daemon.utils.stale_checkouts import (
    DaemonProcess,
    StaleDaemon,
    StaleWorktree,
    collect_stale_report,
    default_daemon_processes,
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

    def test_missing_directory_with_merged_branch_also_offers_branch_delete(
        self, repo: Path, tmp_path: Path
    ) -> None:
        wt = _add_worktree(repo, tmp_path, "gone-merged")
        _commit(wt, "x.txt")
        _git(repo, "merge", "--no-ff", "gone-merged", "-m", "merge")
        shutil.rmtree(wt)

        found = find_stale_worktrees(
            repo, "main", now=time.time(), age_fn=_old, process_cwds_fn=_no_processes
        )

        assert len(found) == 1
        assert any("merged into main" in reason for reason in found[0].reasons)
        assert found[0].commands == ("git worktree prune", "git branch -d gone-merged")

    def test_detached_worktree_is_never_reported_while_its_directory_exists(
        self, repo: Path, tmp_path: Path
    ) -> None:
        path = tmp_path / "wt-detached"
        _git(repo, "worktree", "add", "--detach", str(path))

        found = find_stale_worktrees(
            repo, "main", now=time.time(), age_fn=_very_old, process_cwds_fn=_no_processes
        )

        assert found == ()

    def test_detached_worktree_with_missing_directory_is_prunable_without_branch_delete(
        self, repo: Path, tmp_path: Path
    ) -> None:
        path = tmp_path / "wt-detached"
        _git(repo, "worktree", "add", "--detach", str(path))
        shutil.rmtree(path)

        found = find_stale_worktrees(
            repo, "main", now=time.time(), age_fn=_old, process_cwds_fn=_no_processes
        )

        assert len(found) == 1
        assert found[0].branch is None
        assert found[0].commands == ("git worktree prune",)

    def test_worktree_on_the_base_branch_is_never_reported(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _add_worktree(repo, tmp_path, "trunk")

        found = find_stale_worktrees(
            repo, "trunk", now=time.time(), age_fn=_very_old, process_cwds_fn=_no_processes
        )

        assert found == ()

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


def _pid_file(directory: Path, text: str, name: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (pid_file_name() if name is None else name)
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
            processes_fn=lambda: (DaemonProcess(pid=4242, root=str(root), root_exists=True),),
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
        # `stop` leaves a stale pid file in place (it prints "not running"), so
        # the only remedy that clears it is removing exactly this file.
        assert [shlex.split(command) for command in found[0].commands] == [
            ["rm", "--", str(pid_file)]
        ]
        assert not any("stop" in command for command in found[0].commands)

    def test_remedy_names_a_path_with_spaces_as_one_argument(self, tmp_path: Path) -> None:
        root = tmp_path / "my proj"
        pid_file = _pid_file(_untracked(root), "4242\n", name=pid_file_name())

        found = find_stale_daemons(
            (root,),
            processes_fn=_no_daemons,
            pid_alive_fn=_dead,
            untracked_dir_fn=_untracked,
        )

        assert shlex.split(found[0].commands[0]) == ["rm", "--", str(pid_file)]

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

    def test_another_hosts_pid_file_is_never_read(self, tmp_path: Path) -> None:
        """Another host's pid names a process in a pid namespace this host cannot probe."""
        root = tmp_path / "proj"
        _pid_file(_untracked(root), "4242\n", name="daemon-some-other-host.pid")

        found = find_stale_daemons(
            (root,),
            processes_fn=_no_daemons,
            pid_alive_fn=_dead,
            untracked_dir_fn=_untracked,
        )

        assert found == ()

    def test_this_hosts_pid_file_name_is_the_one_the_daemon_writes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CLAUDE_HOOKS_PID_PATH", raising=False)
        # A short root: a long one makes get_pid_path fall back to another directory.
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="hk") as short_root:
            assert get_pid_path(Path(short_root)).name == pid_file_name()

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

    def test_daemon_whose_root_is_gone_needs_a_human_look_and_no_signal(self) -> None:
        found = find_stale_daemons(
            (),
            processes_fn=lambda: (DaemonProcess(pid=777, root="/gone", root_exists=False),),
            pid_alive_fn=_alive,
            untracked_dir_fn=_untracked,
        )

        assert len(found) == 1
        assert found[0].subject == "daemon pid 777"
        assert "/gone" in found[0].reason
        assert "human" in found[0].reason
        # Never an unproven signal: only read-only inspection is offered.
        assert found[0].commands == ("ps -p 777 -o lstart,args",)
        assert not any("kill" in command for command in found[0].commands)

    def test_daemon_process_with_unknown_root_is_left_alone(self) -> None:
        """A daemon this check cannot attribute is never reported."""
        found = find_stale_daemons(
            (),
            processes_fn=lambda: (DaemonProcess(pid=777, root=None, root_exists=None),),
            pid_alive_fn=_alive,
            untracked_dir_fn=_untracked,
        )

        assert found == ()

    def test_daemon_whose_root_cannot_be_checked_is_not_stale(self) -> None:
        found = find_stale_daemons(
            (),
            processes_fn=lambda: (DaemonProcess(pid=777, root="/x", root_exists=None),),
            pid_alive_fn=_alive,
            untracked_dir_fn=_untracked,
        )

        assert found == ()

    def test_daemon_process_with_existing_root_is_not_stale(self) -> None:
        found = find_stale_daemons(
            (),
            processes_fn=lambda: (DaemonProcess(pid=777, root="/x", root_exists=True),),
            pid_alive_fn=_alive,
            untracked_dir_fn=_untracked,
        )

        assert found == ()


def _fake_proc(tmp_path: Path, pid: int, *, root_contains: str | None) -> Path:
    """A fake /proc whose ``<pid>/root`` holds ``root_contains`` (None: no such pid)."""
    proc = tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    if root_contains is not None:
        (proc / str(pid) / "root" / root_contains.lstrip("/")).mkdir(parents=True)
    return proc


class TestDefaultDaemonProcesses:
    @staticmethod
    def _proof(root: str | None) -> RootProof:
        return RootProof(root=root, refusal=None if root else "no root")

    def test_root_is_judged_in_the_daemons_own_namespace(self, tmp_path: Path) -> None:
        """A root present for the daemon but absent here is NOT stale."""
        proc = _fake_proc(tmp_path, 10, root_contains="/container/workspace")

        found = default_daemon_processes(
            find_fn=lambda: [10],
            root_fn=lambda _pid: self._proof("/container/workspace"),
            owner_fn=lambda _pid: True,
            proc_dir=proc,
        )

        assert found == (DaemonProcess(pid=10, root="/container/workspace", root_exists=True),)
        assert not Path("/container/workspace").exists()

    def test_root_missing_in_the_daemons_namespace_is_reported_absent(self, tmp_path: Path) -> None:
        proc = _fake_proc(tmp_path, 10, root_contains="/other")

        found = default_daemon_processes(
            find_fn=lambda: [10],
            root_fn=lambda _pid: self._proof("/deleted"),
            owner_fn=lambda _pid: True,
            proc_dir=proc,
        )

        assert found == (DaemonProcess(pid=10, root="/deleted", root_exists=False),)

    def test_unreadable_namespace_is_unknown_not_absent(self, tmp_path: Path) -> None:
        proc = _fake_proc(tmp_path, 10, root_contains=None)

        found = default_daemon_processes(
            find_fn=lambda: [10],
            root_fn=lambda _pid: self._proof("/anything"),
            owner_fn=lambda _pid: True,
            proc_dir=proc,
        )

        assert found == (DaemonProcess(pid=10, root="/anything", root_exists=None),)

    def test_another_users_daemon_is_skipped(self, tmp_path: Path) -> None:
        proc = _fake_proc(tmp_path, 10, root_contains="/x")

        found = default_daemon_processes(
            find_fn=lambda: [10],
            root_fn=lambda _pid: self._proof("/gone"),
            owner_fn=lambda _pid: False,
            proc_dir=proc,
        )

        assert found == ()

    def test_unattributable_daemon_has_no_root(self, tmp_path: Path) -> None:
        found = default_daemon_processes(
            find_fn=lambda: [10],
            root_fn=lambda _pid: self._proof(None),
            owner_fn=lambda _pid: True,
            proc_dir=tmp_path,
        )

        assert found == (DaemonProcess(pid=10, root=None, root_exists=None),)

    def test_no_daemons_running(self) -> None:
        assert default_daemon_processes(find_fn=list) == ()


class TestCollectStaleReport:
    def test_quiet_for_a_repo_with_nothing_stale(self, repo: Path) -> None:
        assert collect_stale_report(repo, "main", processes_fn=_no_daemons) is None

    def test_reports_a_missing_worktree(self, repo: Path, tmp_path: Path) -> None:
        wt = _add_worktree(repo, tmp_path, "gone")
        shutil.rmtree(wt)

        report = collect_stale_report(repo, "main", processes_fn=_no_daemons)

        assert report is not None
        assert "STALE CHECKOUTS" in report
        assert "git worktree prune" in report

    def test_reports_a_daemon_whose_root_is_gone(self, repo: Path) -> None:
        report = collect_stale_report(
            repo,
            "main",
            processes_fn=lambda: (DaemonProcess(pid=5, root="/gone", root_exists=False),),
        )

        assert report is not None
        assert "daemon pid 5" in report


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
            commands=("ps -p 9 -o lstart,args",),
        )

        report = render_stale_report((worktree,), (daemon,))

        assert report is not None
        assert "/w/a" in report
        assert "branch fully merged into main" in report
        assert "git worktree remove /w/a" in report
        assert "git branch -d a" in report
        assert "daemon pid 9" in report
        assert "ps -p 9 -o lstart,args" in report
        assert "does not run" in report

    def test_worktree_heading_absent_when_only_daemons_are_stale(self) -> None:
        daemon = StaleDaemon(subject="s", reason="r", commands=("true",))

        report = render_stale_report((), (daemon,))

        assert report is not None
        assert "Stale worktrees" not in report
        assert "Stale daemons" in report
