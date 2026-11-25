"""Scratch entry liveness (Plan 00627 Task 1.5, DESIGN.md section 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.scratch_liveness import (
    BackgroundRecords,
    LivenessInputs,
    entry_liveness,
    read_background_records,
    read_process_cwds,
)

_NOW = 2_000_000_000.0
_NS = 1_000_000_000
_OLD_CTIME_NS = int((_NOW - 10 * 3600) * _NS)


def _inputs(
    *,
    cwds: dict[int, Path] | None = None,
    commands: tuple[str, ...] = (),
    error: str = "",
    min_age_minutes: int = 30,
) -> LivenessInputs:
    return LivenessInputs(
        cwds=cwds or {},
        background=BackgroundRecords(commands=commands, error=error),
        min_age_minutes=min_age_minutes,
        now=_NOW,
    )


ENTRY = Path("/p/untracked/scratch/probe")


class TestReadProcessCwds:
    """F-BYPS low: a pid whose cwd cannot be read is reported, never silently skipped."""

    def test_reads_each_pid_cwd_and_names_the_unreadable_ones(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        work = tmp_path / "work"
        work.mkdir()
        (proc / "123").mkdir(parents=True)
        (proc / "123" / "cwd").symlink_to(work)
        (proc / "124").mkdir()  # exited between listing and reading: no cwd at all
        (proc / "125" / "cwd").mkdir(parents=True)  # not a link: readlink fails
        (proc / "self").mkdir()
        reading = read_process_cwds(proc_root=proc, own_pid=999)
        assert dict(reading.cwds) == {123: work.resolve()}
        assert reading.unreadable == (125,)

    def test_a_non_dumpable_agent_is_not_an_unreadable_process(self, tmp_path: Path) -> None:
        # ssh-agent and gpg-agent mark themselves non-dumpable, so without
        # CAP_SYS_PTRACE their /proc/<pid>/cwd refuses even root. One such
        # agent in the container must not make every sweep and every worktree
        # evacuation "classification incomplete" for ever.
        proc = tmp_path / "proc"
        (proc / "51" / "cwd").mkdir(parents=True)  # not a link: readlink fails
        (proc / "51" / "comm").write_text("ssh-agent\n", encoding="utf-8")
        (proc / "52" / "cwd").mkdir(parents=True)
        (proc / "52" / "comm").write_text("some-worker\n", encoding="utf-8")
        reading = read_process_cwds(proc_root=proc, own_pid=999)
        assert reading.unreadable == (52,)

    def test_a_gpg_agent_is_not_an_unreadable_process_either(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        (proc / "61" / "cwd").mkdir(parents=True)
        (proc / "61" / "comm").write_text("gpg-agent\n", encoding="utf-8")
        reading = read_process_cwds(proc_root=proc, own_pid=999)
        assert reading.unreadable == ()

    def test_a_pid_with_no_readable_comm_stays_unreadable(self, tmp_path: Path) -> None:
        """Without a comm to name the process, the fail-closed rule still applies."""
        proc = tmp_path / "proc"
        (proc / "71" / "cwd").mkdir(parents=True)  # cwd unreadable, and no comm file at all
        reading = read_process_cwds(proc_root=proc, own_pid=999)
        assert reading.unreadable == (71,)

    def test_skips_its_own_pid(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        (proc / "7").mkdir(parents=True)
        (proc / "7" / "cwd").symlink_to(tmp_path)
        reading = read_process_cwds(proc_root=proc, own_pid=7)
        assert dict(reading.cwds) == {}
        assert reading.unreadable == ()

    def test_no_proc_root_reads_nothing(self, tmp_path: Path) -> None:
        reading = read_process_cwds(proc_root=tmp_path / "absent", own_pid=1)
        assert dict(reading.cwds) == {}
        assert reading.unreadable == ()


def _process(proc: Path, pid: int, cwd: Path) -> Path:
    entry = proc / str(pid)
    entry.mkdir(parents=True)
    (entry / "cwd").symlink_to(cwd)
    return entry


class TestReadOpenFiles:
    """DESIGN.md open-descriptor row: a file held open inside an entry is seen.

    A process whose working directory is elsewhere can hold a descriptor or a
    memory map on a file in the entry; a write through it after the pack would
    land in an unlinked inode and be lost.
    """

    def test_each_descriptor_link_to_a_path_is_read(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        entry = _process(proc, 40, tmp_path)
        (entry / "fd").mkdir()
        (entry / "fd" / "0").symlink_to("/dev/null")
        (entry / "fd" / "3").symlink_to("/p/untracked/scratch/e/log")
        (entry / "fd" / "4").symlink_to("socket:[123]")
        (entry / "fd" / "5").symlink_to("pipe:[9]")
        (entry / "fd" / "6").symlink_to("anon_inode:[eventpoll]")
        reading = read_process_cwds(proc_root=proc, own_pid=999)
        assert set(reading.open_paths[40]) == {
            Path("/dev/null"),
            Path("/p/untracked/scratch/e/log"),
        }
        assert reading.unreadable == ()

    def test_a_deleted_file_still_names_where_it_was(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        entry = _process(proc, 41, tmp_path)
        (entry / "fd").mkdir()
        (entry / "fd" / "3").symlink_to("/p/untracked/scratch/e/log (deleted)")
        reading = read_process_cwds(proc_root=proc, own_pid=999)
        assert reading.open_paths[41] == (Path("/p/untracked/scratch/e/log"),)

    def test_each_mapped_file_is_read(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        entry = _process(proc, 42, tmp_path)
        (entry / "maps").write_text(
            "7f00-7f01 r-xp 00000000 08:01 12 /p/untracked/scratch/e/lib.so\n"
            "7f01-7f02 rw-p 00000000 00:00 0 \n"
            "7f02-7f03 rw-p 00000000 00:00 0 [heap]\n"
            "7f03-7f04 rw-s 00000000 08:01 13 /p/untracked/scratch/e/a b.db\n",
            encoding="utf-8",
        )
        reading = read_process_cwds(proc_root=proc, own_pid=999)
        assert set(reading.open_paths[42]) == {
            Path("/p/untracked/scratch/e/lib.so"),
            Path("/p/untracked/scratch/e/a b.db"),
        }

    def test_an_unlistable_descriptor_table_makes_the_pid_unreadable(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        entry = _process(proc, 43, tmp_path)
        (entry / "fd").write_text("not a directory", encoding="utf-8")
        reading = read_process_cwds(proc_root=proc, own_pid=999)
        assert reading.unreadable == (43,)

    def test_an_unreadable_map_makes_the_pid_unreadable(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        entry = _process(proc, 44, tmp_path)
        (entry / "maps").mkdir()  # reading a directory fails
        reading = read_process_cwds(proc_root=proc, own_pid=999)
        assert reading.unreadable == (44,)

    def test_an_unreadable_descriptor_link_makes_the_pid_unreadable(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        entry = _process(proc, 45, tmp_path)
        (entry / "fd").mkdir()
        (entry / "fd" / "3").mkdir()  # not a link: readlink fails with EINVAL
        reading = read_process_cwds(proc_root=proc, own_pid=999)
        assert reading.unreadable == (45,)

    def test_an_exited_process_holds_nothing_open(self, tmp_path: Path) -> None:
        """No ``fd`` or ``maps`` at all: the process is gone, so it holds no file."""
        proc = tmp_path / "proc"
        _process(proc, 46, tmp_path)
        reading = read_process_cwds(proc_root=proc, own_pid=999)
        assert reading.open_paths.get(46, ()) == ()
        assert reading.unreadable == ()

    def test_this_process_own_open_file_is_seen_on_the_real_proc(self, tmp_path: Path) -> None:
        held = tmp_path / "held.log"
        with held.open("w", encoding="utf-8"):
            reading = read_process_cwds(own_pid=-1)
        import os

        assert held in reading.open_paths.get(os.getpid(), ())


class TestReadBackgroundRecords:
    def test_a_missing_file_is_no_records(self, tmp_path: Path) -> None:
        records = read_background_records(tmp_path / "absent.jsonl")
        assert records == BackgroundRecords(commands=(), error="")

    def test_commands_are_read_and_blank_lines_skipped(self, tmp_path: Path) -> None:
        state = tmp_path / "bg.jsonl"
        lines = [json.dumps({"command": "sleep 1 &", "session_id": "s"}), "", "  "]
        state.write_text("\n".join(lines) + "\n")
        assert read_background_records(state) == BackgroundRecords(("sleep 1 &",), "")

    def test_a_record_without_a_command_contributes_nothing(self, tmp_path: Path) -> None:
        state = tmp_path / "bg.jsonl"
        state.write_text(json.dumps({"session_id": "s"}) + "\n")
        assert read_background_records(state) == BackgroundRecords((), "")

    def test_a_malformed_line_is_an_error_never_skipped(self, tmp_path: Path) -> None:
        state = tmp_path / "bg.jsonl"
        state.write_text('{"command": "a"}\nnot json\n')
        records = read_background_records(state)
        assert records.error
        assert "line 2" in records.error

    def test_a_line_that_is_not_an_object_is_an_error(self, tmp_path: Path) -> None:
        state = tmp_path / "bg.jsonl"
        state.write_text('["a"]\n')
        assert read_background_records(state).error

    def test_a_non_string_command_is_an_error(self, tmp_path: Path) -> None:
        state = tmp_path / "bg.jsonl"
        state.write_text('{"command": 3}\n')
        assert read_background_records(state).error

    def test_an_unreadable_file_is_an_error(self, tmp_path: Path) -> None:
        state = tmp_path / "bg.jsonl"
        state.mkdir()
        records = read_background_records(state)
        assert records.error
        assert "IsADirectoryError" in records.error

    def test_undecodable_bytes_are_an_error(self, tmp_path: Path) -> None:
        state = tmp_path / "bg.jsonl"
        state.write_bytes(b"\xff\xfe\n")
        assert read_background_records(state).error


class TestProcessCwds:
    def test_a_cwd_at_the_entry_is_live(self) -> None:
        reasons = entry_liveness(
            ENTRY,
            relative=None,
            root_ctime_ns=_OLD_CTIME_NS,
            birth=None,
            inputs=_inputs(cwds={42: ENTRY}),
        )
        assert reasons == ("process 42 has its working directory inside the entry",)

    def test_a_cwd_below_the_entry_is_live(self) -> None:
        reasons = entry_liveness(
            ENTRY,
            relative=None,
            root_ctime_ns=_OLD_CTIME_NS,
            birth=None,
            inputs=_inputs(cwds={7: ENTRY / "a" / "b"}),
        )
        assert len(reasons) == 1

    def test_a_sibling_sharing_a_prefix_is_not_live(self) -> None:
        reasons = entry_liveness(
            ENTRY,
            relative=None,
            root_ctime_ns=_OLD_CTIME_NS,
            birth=None,
            inputs=_inputs(cwds={7: Path("/p/untracked/scratch/probe-2")}),
        )
        assert reasons == ()

    def test_a_cwd_above_the_entry_is_not_live(self) -> None:
        reasons = entry_liveness(
            ENTRY,
            relative=None,
            root_ctime_ns=_OLD_CTIME_NS,
            birth=None,
            inputs=_inputs(cwds={7: ENTRY.parent}),
        )
        assert reasons == ()


class TestBackgroundCommands:
    def test_a_command_naming_the_absolute_path_is_live(self) -> None:
        reasons = entry_liveness(
            ENTRY,
            relative=None,
            root_ctime_ns=_OLD_CTIME_NS,
            birth=None,
            inputs=_inputs(commands=(f"python {ENTRY}/run.py &",)),
        )
        assert reasons == ("a tracked background command names the entry",)

    def test_a_command_naming_the_relative_path_is_live(self) -> None:
        reasons = entry_liveness(
            ENTRY,
            relative="untracked/scratch/probe",
            root_ctime_ns=_OLD_CTIME_NS,
            birth=None,
            inputs=_inputs(commands=("cd untracked/scratch/probe && make &",)),
        )
        assert reasons == ("a tracked background command names the entry",)

    def test_an_unrelated_command_is_not_live(self) -> None:
        reasons = entry_liveness(
            ENTRY,
            relative="untracked/scratch/probe",
            root_ctime_ns=_OLD_CTIME_NS,
            birth=None,
            inputs=_inputs(commands=("sleep 600 &",)),
        )
        assert reasons == ()

    def test_unreadable_records_make_every_entry_live(self) -> None:
        reasons = entry_liveness(
            ENTRY,
            relative=None,
            root_ctime_ns=_OLD_CTIME_NS,
            birth=None,
            inputs=_inputs(error="bg.jsonl line 2 is not JSON"),
        )
        assert reasons == (
            "background-process records could not be read (bg.jsonl line 2 is not JSON)",
        )


class TestMinimumAge:
    def test_a_young_root_ctime_is_live(self) -> None:
        reasons = entry_liveness(
            ENTRY,
            relative=None,
            root_ctime_ns=int((_NOW - 60) * _NS),
            birth=None,
            inputs=_inputs(min_age_minutes=30),
        )
        assert reasons == ("younger than the minimum age of 30 minutes",)

    def test_a_young_birth_is_live(self) -> None:
        reasons = entry_liveness(
            ENTRY,
            relative=None,
            root_ctime_ns=_OLD_CTIME_NS,
            birth=_NOW - 60,
            inputs=_inputs(min_age_minutes=30),
        )
        assert reasons == ("younger than the minimum age of 30 minutes",)

    def test_an_old_entry_is_not_live(self) -> None:
        reasons = entry_liveness(
            ENTRY,
            relative=None,
            root_ctime_ns=_OLD_CTIME_NS,
            birth=_NOW - 7200,
            inputs=_inputs(min_age_minutes=30),
        )
        assert reasons == ()

    @pytest.mark.parametrize("minutes", [0])
    def test_a_zero_minimum_age_never_makes_an_entry_live(self, minutes: int) -> None:
        reasons = entry_liveness(
            ENTRY,
            relative=None,
            root_ctime_ns=int(_NOW * _NS),
            birth=None,
            inputs=_inputs(min_age_minutes=minutes),
        )
        assert reasons == ()


def test_every_reason_is_reported() -> None:
    reasons = entry_liveness(
        ENTRY,
        relative=None,
        root_ctime_ns=int((_NOW - 60) * _NS),
        birth=None,
        inputs=_inputs(cwds={1: ENTRY}, commands=(str(ENTRY),)),
    )
    assert len(reasons) == 3
