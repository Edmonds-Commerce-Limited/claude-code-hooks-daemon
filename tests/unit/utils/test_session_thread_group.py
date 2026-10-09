"""Thread grouping of Claude Code sessions by process ancestry (Plan 00470 Task 6.4).

Every thread of one Claude Code session runs under one ``claude daemon run
--spawned-by`` process. These tests build fake ``/proc`` trees in a tmp dir; no
real process is inspected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.session_thread_group import (
    ThreadGroup,
    ThreadGroupRegistry,
    find_thread_group,
)

DAEMON_ARGV = ["claude", "daemon", "run", "--origin", "transient", "--spawned-by", '{"pid":1}']


def add_proc(
    root: Path,
    pid: int,
    ppid: int,
    argv: list[str],
    *,
    start: int = 1000,
    comm: str = "claude",
) -> None:
    """Write one fake /proc/<pid> with a stat line and a cmdline."""
    proc = root / str(pid)
    proc.mkdir(parents=True)
    # Field layout after the ')' is: state ppid pgrp session tty tpgid flags minflt cminflt
    # majflt cmajflt utime stime cutime cstime priority nice threads itrealvalue starttime ...
    rest = ["S", str(ppid)] + ["0"] * 17 + [str(start), "0", "0"]
    (proc / "stat").write_text(f"{pid} ({comm}) {' '.join(rest)}\n")
    (proc / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


@pytest.fixture
def proc_root(tmp_path: Path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    return root


class TestFindThreadGroup:
    def test_finds_the_nearest_daemon_run_ancestor(self, proc_root: Path) -> None:
        add_proc(proc_root, 1, 0, ["init"])
        add_proc(proc_root, 580, 1, ["claude"], start=500)
        add_proc(proc_root, 589, 580, DAEMON_ARGV, start=777)
        add_proc(proc_root, 590, 589, ["claude", "bg-pty-host", "--bg-pty-host", "x"])
        add_proc(proc_root, 591, 590, ["2.1.292", "--session-id", "abc"])
        add_proc(proc_root, 700, 591, ["relay"])

        group = find_thread_group(700, proc_root=proc_root)

        assert group == ThreadGroup(pid=589, start_time=777)
        assert group is not None
        assert group.key == "589:777"

    def test_comm_with_spaces_and_parens_still_parses(self, proc_root: Path) -> None:
        add_proc(proc_root, 589, 1, DAEMON_ARGV, start=9, comm="we ird) (name")
        add_proc(proc_root, 700, 589, ["relay"])

        assert find_thread_group(700, proc_root=proc_root) == ThreadGroup(589, 9)

    def test_no_daemon_run_ancestor_is_none(self, proc_root: Path) -> None:
        add_proc(proc_root, 1, 0, ["init"])
        add_proc(proc_root, 2249, 1, ["claude"])
        add_proc(proc_root, 2300, 2249, ["relay"])

        assert find_thread_group(2300, proc_root=proc_root) is None

    def test_a_daemon_run_without_spawned_by_is_not_a_session_front_end(
        self, proc_root: Path
    ) -> None:
        add_proc(proc_root, 589, 1, ["claude", "daemon", "run", "--origin", "x"])
        add_proc(proc_root, 700, 589, ["relay"])

        assert find_thread_group(700, proc_root=proc_root) is None

    def test_unreadable_proc_is_none(self, tmp_path: Path) -> None:
        assert find_thread_group(700, proc_root=tmp_path / "missing") is None

    def test_a_broken_link_in_the_chain_is_none(self, proc_root: Path) -> None:
        add_proc(proc_root, 700, 650, ["relay"])  # parent 650 has no /proc entry

        assert find_thread_group(700, proc_root=proc_root) is None

    def test_a_malformed_stat_is_none(self, proc_root: Path) -> None:
        add_proc(proc_root, 700, 1, ["relay"])
        (proc_root / "700" / "stat").write_text("garbage")

        assert find_thread_group(700, proc_root=proc_root) is None

    def test_a_ppid_cycle_is_bounded(self, proc_root: Path) -> None:
        add_proc(proc_root, 10, 11, ["a"])
        add_proc(proc_root, 11, 10, ["b"])

        assert find_thread_group(10, proc_root=proc_root, max_depth=8) is None

    def test_depth_limit_stops_the_walk(self, proc_root: Path) -> None:
        add_proc(proc_root, 589, 1, DAEMON_ARGV)
        parent = 589
        for pid in range(600, 610):
            add_proc(proc_root, pid, parent, ["x"])
            parent = pid

        assert find_thread_group(609, proc_root=proc_root, max_depth=3) is None
        assert find_thread_group(609, proc_root=proc_root, max_depth=20) is not None

    def test_deadline_stops_the_walk(self, proc_root: Path) -> None:
        add_proc(proc_root, 589, 1, DAEMON_ARGV)
        add_proc(proc_root, 700, 589, ["relay"])
        ticks = iter([0.0, 5.0, 10.0, 15.0])

        group = find_thread_group(
            700, proc_root=proc_root, time_budget=1.0, clock=lambda: next(ticks)
        )

        assert group is None

    @pytest.mark.parametrize("pid", [0, 1, -5])
    def test_non_process_pids_are_none(self, proc_root: Path, pid: int) -> None:
        assert find_thread_group(pid, proc_root=proc_root) is None


class TestThreadGroupRegistry:
    def test_first_session_per_group_is_the_holder(self, tmp_path: Path) -> None:
        registry = ThreadGroupRegistry(tmp_path / "groups.json")
        group = ThreadGroup(589, 777)

        assert registry.claim(group, "first") == "first"
        assert registry.claim(group, "second") == "first"
        assert registry.claim(group, "first") == "first"

    def test_the_mapping_survives_a_new_registry_object(self, tmp_path: Path) -> None:
        path = tmp_path / "untracked" / "groups.json"
        ThreadGroupRegistry(path).claim(ThreadGroup(589, 777), "first")

        assert ThreadGroupRegistry(path).claim(ThreadGroup(589, 777), "second") == "first"

    def test_pid_reuse_with_a_new_start_time_is_a_new_group(self, tmp_path: Path) -> None:
        registry = ThreadGroupRegistry(tmp_path / "groups.json")
        registry.claim(ThreadGroup(589, 777), "old")

        assert registry.claim(ThreadGroup(589, 99999), "new") == "new"

    def test_different_groups_are_independent(self, tmp_path: Path) -> None:
        registry = ThreadGroupRegistry(tmp_path / "groups.json")
        registry.claim(ThreadGroup(1, 1), "a")

        assert registry.claim(ThreadGroup(2, 2), "b") == "b"

    def test_a_corrupt_file_means_the_caller_holds(self, tmp_path: Path) -> None:
        path = tmp_path / "groups.json"
        path.write_text("{not json")

        assert ThreadGroupRegistry(path).claim(ThreadGroup(1, 1), "a") == "a"

    def test_an_unwritable_location_means_the_caller_holds(self, tmp_path: Path) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("x")
        registry = ThreadGroupRegistry(blocker / "groups.json")  # parent is a file

        assert registry.claim(ThreadGroup(1, 1), "a") == "a"
        assert registry.claim(ThreadGroup(1, 1), "b") == "b"

    def test_oldest_groups_are_dropped_beyond_the_bound(self, tmp_path: Path) -> None:
        registry = ThreadGroupRegistry(tmp_path / "groups.json", max_groups=2)
        for n in (1, 2, 3):
            registry.claim(ThreadGroup(n, n), f"s{n}")

        # group 1 was evicted, so a new session now becomes its holder.
        assert registry.claim(ThreadGroup(1, 1), "late") == "late"
        assert registry.claim(ThreadGroup(3, 3), "other") == "s3"

    def test_empty_session_id_is_rejected(self, tmp_path: Path) -> None:
        registry = ThreadGroupRegistry(tmp_path / "groups.json")

        with pytest.raises(ValueError, match="session_id"):
            registry.claim(ThreadGroup(1, 1), "")
