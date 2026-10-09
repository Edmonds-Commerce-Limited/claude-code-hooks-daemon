"""Thread grouping of Claude Code sessions by process ancestry (Plan 00470 Task 6.4).

Every thread of one Claude Code session runs under one ``claude daemon run
--origin transient --spawned-by`` process. These tests build fake ``/proc``
trees in a tmp dir; no real process is inspected.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.utils import session_thread_group
from claude_code_hooks_daemon.utils.session_thread_group import (
    OtherHolder,
    ProcessId,
    ThreadGroupRegistry,
    ThreadPlacement,
    WorkerKind,
    find_thread_placement,
    initial_thread_holder_elsewhere,
)
from tests.fake_proc import (
    DAEMON_ARGV,
    INITIAL_WORKER_ARGV,
    SPARE_WORKER_ARGV,
    add_proc,
    add_thread,
    remove_proc,
)

DAEMON = 589


@pytest.fixture
def proc_root(tmp_path: Path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    add_proc(root, 1, 0, ["init"])
    add_proc(root, 580, 1, ["claude"], start=500)
    add_proc(root, DAEMON, 580, DAEMON_ARGV, start=777)
    return root


class TestFindThreadPlacement:
    def test_finds_the_daemon_run_ancestor_and_the_initial_worker(self, proc_root: Path) -> None:
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV, worker_start=42)

        placement = find_thread_placement(700, proc_root=proc_root)

        assert placement is not None
        assert placement.group == ProcessId(DAEMON, 777)
        assert placement.group.key == "589:777"
        assert placement.worker == ProcessId(591, 42)
        assert placement.kind is WorkerKind.INITIAL

    def test_a_bg_spare_worker_is_a_later_thread(self, proc_root: Path) -> None:
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)

        placement = find_thread_placement(701, proc_root=proc_root)

        assert placement is not None
        assert placement.kind is WorkerKind.SPARE
        assert placement.worker == ProcessId(592, 1000)

    def test_an_unrecognised_worker_shape_is_unknown(self, proc_root: Path) -> None:
        add_thread(proc_root, DAEMON, 593, 702, ["something", "else"])

        placement = find_thread_placement(702, proc_root=proc_root)

        assert placement is not None
        assert placement.kind is WorkerKind.UNKNOWN
        assert placement.worker is None

    def test_resume_alone_is_not_the_initial_shape(self, proc_root: Path) -> None:
        add_thread(proc_root, DAEMON, 594, 703, ["2.1.292", "--resume", "abc"])

        placement = find_thread_placement(703, proc_root=proc_root)

        assert placement is not None
        assert placement.kind is WorkerKind.UNKNOWN

    def test_comm_with_spaces_and_parens_still_parses(self, proc_root: Path) -> None:
        add_proc(proc_root, 595, DAEMON, INITIAL_WORKER_ARGV, start=9, comm="we ird) (name")
        add_proc(proc_root, 704, 595, ["relay"])

        placement = find_thread_placement(704, proc_root=proc_root)

        assert placement is not None
        assert placement.worker == ProcessId(595, 9)

    def test_no_daemon_run_ancestor_is_none(self, tmp_path: Path) -> None:
        root = tmp_path / "p"
        root.mkdir()
        add_proc(root, 1, 0, ["init"])
        add_proc(root, 2249, 1, ["claude"])
        add_proc(root, 2300, 2249, ["relay"])

        assert find_thread_placement(2300, proc_root=root) is None

    @pytest.mark.parametrize(
        "argv",
        [
            ["claude", "daemon", "run", "--origin", "x"],  # no --spawned-by
            ["claude", "daemon", "run", "--spawned-by", '{"pid":1}'],  # no origin
            ["claude", "daemon", "run", "--origin", "resident", "--spawned-by", '{"pid":1}'],
            ["claude", "daemon", "run", "--origin", "transient", "--spawned-by", "notjson"],
            ["claude", "daemon", "run", "--origin", "transient", "--spawned-by"],
            ["claude", "daemon", "status", "--origin", "transient", "--spawned-by", '{"pid":1}'],
        ],
    )
    def test_only_a_transient_spawned_by_daemon_run_is_a_session_front_end(
        self, tmp_path: Path, argv: list[str]
    ) -> None:
        root = tmp_path / "p"
        root.mkdir()
        add_proc(root, 589, 1, argv)
        add_thread(root, 589, 591, 700, INITIAL_WORKER_ARGV)

        assert find_thread_placement(700, proc_root=root) is None

    def test_unreadable_proc_is_none(self, tmp_path: Path) -> None:
        assert find_thread_placement(700, proc_root=tmp_path / "missing") is None

    def test_a_broken_link_in_the_chain_is_none(self, proc_root: Path) -> None:
        add_proc(proc_root, 700, 650, ["relay"])  # parent 650 has no /proc entry

        assert find_thread_placement(700, proc_root=proc_root) is None

    def test_a_malformed_stat_is_none(self, proc_root: Path) -> None:
        add_proc(proc_root, 700, 1, ["relay"])
        (proc_root / "700" / "stat").write_text("garbage")

        assert find_thread_placement(700, proc_root=proc_root) is None

    def test_a_ppid_cycle_is_bounded(self, proc_root: Path) -> None:
        add_proc(proc_root, 10, 11, ["a"])
        add_proc(proc_root, 11, 10, ["b"])

        assert find_thread_placement(10, proc_root=proc_root, max_depth=8) is None

    def test_depth_limit_stops_the_walk(self, proc_root: Path) -> None:
        parent = DAEMON
        for pid in range(600, 610):
            add_proc(proc_root, pid, parent, ["x"])
            parent = pid

        assert find_thread_placement(609, proc_root=proc_root, max_depth=3) is None
        assert find_thread_placement(609, proc_root=proc_root, max_depth=20) is not None

    def test_deadline_stops_the_walk(self, proc_root: Path) -> None:
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)
        ticks = iter([0.0, 5.0, 10.0, 15.0])

        placement = find_thread_placement(
            700, proc_root=proc_root, time_budget=1.0, clock=lambda: next(ticks)
        )

        assert placement is None

    @pytest.mark.parametrize("pid", [0, 1, -5])
    def test_non_process_pids_are_none(self, proc_root: Path, pid: int) -> None:
        assert find_thread_placement(pid, proc_root=proc_root) is None


def _placement(proc_root: Path, hook_pid: int) -> ThreadPlacement:
    placement = find_thread_placement(hook_pid, proc_root=proc_root)
    assert placement is not None
    return placement


class TestRegistryResolve:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> ThreadGroupRegistry:
        return ThreadGroupRegistry(tmp_path / "state" / "groups.json")

    def test_the_initial_worker_holds_and_a_spare_is_exempt(
        self, registry: ThreadGroupRegistry, proc_root: Path
    ) -> None:
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)

        assert registry.resolve(_placement(proc_root, 700), "t1", proc_root=proc_root) is None
        other = registry.resolve(_placement(proc_root, 701), "t2", proc_root=proc_root)

        assert other == OtherHolder(session_id="t1")

    def test_a_new_thread_arriving_first_does_not_displace_the_initial_thread(
        self, registry: ThreadGroupRegistry, proc_root: Path
    ) -> None:
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)

        spare_first = registry.resolve(_placement(proc_root, 701), "t2", proc_root=proc_root)
        initial_after = registry.resolve(_placement(proc_root, 700), "t1", proc_root=proc_root)

        assert spare_first == OtherHolder(session_id=None)  # found the live initial worker
        assert initial_after is None  # still holds
        # and the spare is still exempt, now naming the initial thread
        assert registry.resolve(_placement(proc_root, 701), "t2", proc_root=proc_root) == (
            OtherHolder(session_id="t1")
        )

    def test_a_spare_with_no_initial_worker_anywhere_holds(
        self, registry: ThreadGroupRegistry, proc_root: Path
    ) -> None:
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)

        assert registry.resolve(_placement(proc_root, 701), "t2", proc_root=proc_root) is None

    def test_a_scan_that_cannot_finish_leaves_the_spare_holding(
        self, registry: ThreadGroupRegistry, proc_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)
        monkeypatch.setattr(session_thread_group, "MAX_SCAN_ENTRIES", 1)

        assert registry.resolve(_placement(proc_root, 701), "t2", proc_root=proc_root) is None

    def test_holder_exit_hands_the_group_to_the_next_thread(
        self, registry: ThreadGroupRegistry, proc_root: Path
    ) -> None:
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)
        registry.resolve(_placement(proc_root, 700), "t1", proc_root=proc_root)
        placement = _placement(proc_root, 701)
        assert registry.resolve(placement, "t2", proc_root=proc_root) is not None

        remove_proc(proc_root, 700)
        remove_proc(proc_root, 591)

        assert registry.resolve(placement, "t2", proc_root=proc_root) is None
        add_thread(proc_root, DAEMON, 593, 702, SPARE_WORKER_ARGV)
        assert registry.resolve(_placement(proc_root, 702), "t3", proc_root=proc_root) == (
            OtherHolder(session_id="t2")
        )

    def test_a_new_session_id_in_the_holders_own_worker_still_holds(
        self, registry: ThreadGroupRegistry, proc_root: Path
    ) -> None:
        """``/clear`` gives the worker a new session id; the thread is the same."""
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)
        placement = _placement(proc_root, 700)
        registry.resolve(placement, "before-clear", proc_root=proc_root)

        assert registry.resolve(placement, "after-clear", proc_root=proc_root) is None

        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)
        assert registry.resolve(_placement(proc_root, 701), "t2", proc_root=proc_root) == (
            OtherHolder(session_id="after-clear")
        )

    def test_worker_pid_reuse_with_a_new_start_time_is_not_the_holder(
        self, registry: ThreadGroupRegistry, proc_root: Path
    ) -> None:
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV, worker_start=10)
        registry.resolve(_placement(proc_root, 700), "t1", proc_root=proc_root)
        remove_proc(proc_root, 700)
        remove_proc(proc_root, 591)
        add_thread(proc_root, DAEMON, 591, 700, SPARE_WORKER_ARGV, worker_start=99)

        # The recorded holder's pid is alive again, but it is another process.
        assert registry.resolve(_placement(proc_root, 700), "t9", proc_root=proc_root) is None

    def test_ancestor_pid_reuse_with_a_new_start_time_is_a_new_group(
        self, registry: ThreadGroupRegistry, proc_root: Path
    ) -> None:
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)
        registry.resolve(_placement(proc_root, 700), "old", proc_root=proc_root)
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)
        assert registry.resolve(_placement(proc_root, 701), "old2", proc_root=proc_root)

        stat = proc_root / str(DAEMON) / "stat"
        stat.write_text(stat.read_text().replace(" 777 ", " 888 "))
        remove_proc(proc_root, 700)
        remove_proc(proc_root, 591)

        # New group: its initial worker is gone, so the spare holds.
        assert registry.resolve(_placement(proc_root, 701), "new", proc_root=proc_root) is None

    def test_an_unknown_worker_always_holds_and_records_nothing(
        self, registry: ThreadGroupRegistry, proc_root: Path, tmp_path: Path
    ) -> None:
        add_thread(proc_root, DAEMON, 593, 702, ["something", "else"])

        assert registry.resolve(_placement(proc_root, 702), "t", proc_root=proc_root) is None
        assert not (tmp_path / "state" / "groups.json").exists()

    def test_the_mapping_survives_a_new_registry_object(
        self, tmp_path: Path, proc_root: Path
    ) -> None:
        path = tmp_path / "state" / "groups.json"
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)
        ThreadGroupRegistry(path).resolve(_placement(proc_root, 700), "t1", proc_root=proc_root)

        again = ThreadGroupRegistry(path)
        assert again.resolve(_placement(proc_root, 701), "t2", proc_root=proc_root) == (
            OtherHolder(session_id="t1")
        )

    def test_a_corrupt_file_means_the_caller_holds_and_warns_once(
        self, tmp_path: Path, proc_root: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "groups.json"
        path.write_text("{not json")
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)
        placement = _placement(proc_root, 701)
        session_thread_group.reset_warned_paths()

        with caplog.at_level(logging.DEBUG, logger=session_thread_group.logger.name):
            first = ThreadGroupRegistry(path).resolve(placement, "a", proc_root=proc_root)
            path.write_text("{still not json")
            ThreadGroupRegistry(path).resolve(placement, "a", proc_root=proc_root)

        assert first is None
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    def test_an_unwritable_location_means_the_caller_holds(
        self, tmp_path: Path, proc_root: Path
    ) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("x")
        registry = ThreadGroupRegistry(blocker / "groups.json")  # parent is a file
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)

        assert registry.resolve(_placement(proc_root, 700), "a", proc_root=proc_root) is None
        # Nothing was recorded, so the spare finds the live initial worker by scan.
        assert registry.resolve(_placement(proc_root, 701), "b", proc_root=proc_root) == (
            OtherHolder(session_id=None)
        )

    def test_oldest_groups_are_dropped_beyond_the_bound(
        self, tmp_path: Path, proc_root: Path
    ) -> None:
        registry = ThreadGroupRegistry(tmp_path / "groups.json", max_groups=1)
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)
        registry.resolve(_placement(proc_root, 700), "t1", proc_root=proc_root)
        add_proc(proc_root, 900, 1, DAEMON_ARGV, start=5)
        add_thread(proc_root, 900, 901, 902, INITIAL_WORKER_ARGV)
        registry.resolve(_placement(proc_root, 902), "t9", proc_root=proc_root)
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)

        # group DAEMON was evicted, so the spare must rediscover the initial worker.
        assert registry.resolve(_placement(proc_root, 701), "t2", proc_root=proc_root) == (
            OtherHolder(session_id=None)
        )


class TestPolicy:
    @staticmethod
    def _payload(session: str, pid: object) -> dict[str, object]:
        payload: dict[str, object] = {HookInputField.SESSION_ID: session}
        if pid is not None:
            payload[HookInputField.PEER_PID] = pid
        return payload

    def test_the_option_off_reads_nothing(self, tmp_path: Path, proc_root: Path) -> None:
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)

        result = initial_thread_holder_elsewhere(
            self._payload("s", 700),
            initial_thread_only=False,
            registry_path=tmp_path / "g.json",
            proc_root=proc_root,
        )

        assert result is None
        assert not (tmp_path / "g.json").exists()

    @pytest.mark.parametrize("pid", [None, 0, 1, True, "7"])
    def test_an_unusable_pid_means_holds(
        self, tmp_path: Path, proc_root: Path, pid: object
    ) -> None:
        result = initial_thread_holder_elsewhere(
            self._payload("s", pid),
            initial_thread_only=True,
            registry_path=tmp_path / "g.json",
            proc_root=proc_root,
        )

        assert result is None
        assert not (tmp_path / "g.json").exists()

    def test_no_registry_path_means_holds(self, proc_root: Path) -> None:
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)

        result = initial_thread_holder_elsewhere(
            self._payload("s", 701),
            initial_thread_only=True,
            registry_path=None,
            proc_root=proc_root,
        )

        assert result is None

    def test_a_missing_session_id_means_holds(self, tmp_path: Path, proc_root: Path) -> None:
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)

        result = initial_thread_holder_elsewhere(
            self._payload("", 701),
            initial_thread_only=True,
            registry_path=tmp_path / "g.json",
            proc_root=proc_root,
        )

        assert result is None

    def test_a_later_thread_is_exempt_through_the_policy(
        self, tmp_path: Path, proc_root: Path
    ) -> None:
        add_thread(proc_root, DAEMON, 591, 700, INITIAL_WORKER_ARGV)
        add_thread(proc_root, DAEMON, 592, 701, SPARE_WORKER_ARGV)
        path = tmp_path / "g.json"

        first = initial_thread_holder_elsewhere(
            self._payload("t1", 700),
            initial_thread_only=True,
            registry_path=path,
            proc_root=proc_root,
        )
        second = initial_thread_holder_elsewhere(
            self._payload("t2", 701),
            initial_thread_only=True,
            registry_path=path,
            proc_root=proc_root,
        )

        assert first is None
        assert second == OtherHolder(session_id="t1")
