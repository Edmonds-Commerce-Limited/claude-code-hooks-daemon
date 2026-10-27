"""Tests for the /proc descendant-tree session-id helper."""

from pathlib import Path

from claude_code_hooks_daemon.utils.process_tree_sessions import (
    SESSION_ENV_VAR,
    descendant_session_ids,
    session_ids_from_environ,
)


def add_proc(
    root: Path,
    pid: int,
    ppid: int,
    *,
    session_id: str | None = None,
    comm: str = "proc",
    environ_unreadable: bool = False,
) -> None:
    """Create a fake ``/proc/<pid>`` entry under ``root``."""
    entry = root / str(pid)
    entry.mkdir(parents=True)
    (entry / "stat").write_text(f"{pid} ({comm}) S {ppid} 1 1 0 -1\n")
    if environ_unreadable:
        # A directory where the file belongs: read_bytes raises an OSError.
        (entry / "environ").mkdir()
        return
    variables = [b"PATH=/usr/bin"]
    if session_id is not None:
        variables.append(f"{SESSION_ENV_VAR}={session_id}".encode())
    (entry / "environ").write_bytes(b"\x00".join(variables) + b"\x00")


class TestSessionIdsFromEnviron:
    def test_extracts_the_session_variable(self) -> None:
        blob = f"A=1\x00{SESSION_ENV_VAR}=fake-session-a\x00B=2\x00".encode()
        assert session_ids_from_environ(blob) == {"fake-session-a"}

    def test_ignores_similarly_named_variables(self) -> None:
        blob = f"X_{SESSION_ENV_VAR}=nope\x00{SESSION_ENV_VAR}_X=nope\x00".encode()
        assert session_ids_from_environ(blob) == set()

    def test_ignores_an_empty_value(self) -> None:
        assert session_ids_from_environ(f"{SESSION_ENV_VAR}=\x00".encode()) == set()


class TestDescendantSessionIds:
    def test_collects_ids_from_root_and_descendants(self, tmp_path: Path) -> None:
        add_proc(tmp_path, 100, 1)
        add_proc(tmp_path, 101, 100, session_id="fake-session-a")
        add_proc(tmp_path, 102, 101, session_id="fake-session-b")
        assert descendant_session_ids(100, tmp_path) == {"fake-session-a", "fake-session-b"}

    def test_does_not_enter_unrelated_trees(self, tmp_path: Path) -> None:
        add_proc(tmp_path, 100, 1)
        add_proc(tmp_path, 200, 1, session_id="fake-session-other")
        assert descendant_session_ids(100, tmp_path) == frozenset()

    def test_comm_with_parentheses_does_not_break_ppid_parse(self, tmp_path: Path) -> None:
        add_proc(tmp_path, 100, 1)
        add_proc(tmp_path, 101, 100, session_id="fake-session-a", comm="a) S 1 (b")
        assert descendant_session_ids(100, tmp_path) == {"fake-session-a"}

    def test_unreadable_environ_contributes_nothing(self, tmp_path: Path) -> None:
        add_proc(tmp_path, 100, 1)
        add_proc(tmp_path, 101, 100, environ_unreadable=True)
        assert descendant_session_ids(100, tmp_path) == frozenset()

    def test_missing_root_pid_gives_empty_set(self, tmp_path: Path) -> None:
        add_proc(tmp_path, 200, 1, session_id="fake-session-a")
        assert descendant_session_ids(100, tmp_path) == frozenset()

    def test_missing_proc_root_gives_empty_set(self, tmp_path: Path) -> None:
        assert descendant_session_ids(100, tmp_path / "absent") == frozenset()

    def test_ppid_cycle_terminates(self, tmp_path: Path) -> None:
        add_proc(tmp_path, 100, 101, session_id="fake-session-a")
        add_proc(tmp_path, 101, 100)
        assert descendant_session_ids(100, tmp_path) == {"fake-session-a"}

    def test_malformed_stat_is_skipped(self, tmp_path: Path) -> None:
        add_proc(tmp_path, 100, 1)
        add_proc(tmp_path, 101, 100, session_id="fake-session-a")
        (tmp_path / "101" / "stat").write_text("garbage")
        assert descendant_session_ids(100, tmp_path) == frozenset()
