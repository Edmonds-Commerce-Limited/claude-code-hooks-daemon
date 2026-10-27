"""Session scoping of SupervisorIndicatorHandler (issue #140).

A supervisor counts for the rendered session only when that session's id is in
the environ of a process in the supervisor's own descendant tree. The process
table is a fake ``/proc`` built under ``tmp_path`` and injected through
``_proc_root``; nothing here spawns a process or reads the real ``/proc``.
"""

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from tests.unit.utils.test_process_tree_sessions import add_proc

from claude_code_hooks_daemon.handlers.status_line.supervisor_indicator import (
    _BG_GREEN,
    _BG_ORANGE,
    _MAX_TRACKED_SESSIONS,
    SupervisorIndicatorHandler,
)

_MODULE = "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator"
_HANDLER = f"{_MODULE}.SupervisorIndicatorHandler"

_SUPERVISOR_PID = 500
_CLAUDE_PID = 501
_SESSION_A = {"session_id": "fake-session-a"}
_SESSION_B = {"session_id": "fake-session-b"}


def _add_supervisor(proc: Path, *, arm: bool = True) -> None:
    """A supervisor host whose Claude child carries session A."""
    flag = " --arm" if arm else ""
    add_proc(proc, _SUPERVISOR_PID, 1)
    (proc / str(_SUPERVISOR_PID) / "cmdline").write_bytes(
        f"python3\x00claude-supervise.py{flag}\x00".replace(" ", "\x00").encode()
    )
    add_proc(proc, _CLAUDE_PID, _SUPERVISOR_PID, session_id="fake-session-a")
    (proc / str(_CLAUDE_PID) / "cmdline").write_bytes(b"claude\x00")


@pytest.fixture
def proc(tmp_path: Path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    return root


@pytest.fixture
def status_file(tmp_path: Path) -> Path:
    path = tmp_path / "supervisor-status.json"
    path.write_text(json.dumps({"pid": _SUPERVISOR_PID}))
    return path


@pytest.fixture
def missing_status(tmp_path: Path) -> Path:
    return tmp_path / "no-such-status.json"


@pytest.fixture(autouse=True)
def _isolation(tmp_path: Path, proc: Path) -> Iterator[None]:
    with (
        patch(f"{_HANDLER}._message_file_path", return_value=tmp_path / "no-message.json"),
        patch(f"{_HANDLER}._proc_root", return_value=proc),
        patch(f"{_MODULE}.os.kill", return_value=None),
    ):
        yield


def _render(handler: SupervisorIndicatorHandler, status: Path, hook_input: dict[str, str]) -> str:
    with patch(f"{_HANDLER}._status_file_path", return_value=status):
        context = handler.handle(hook_input).context
    return context[0] if context else ""


class TestProcScanIsScopedToTheSession:
    def test_unrelated_supervisor_does_not_turn_an_unsupervised_session_green(
        self, proc: Path, missing_status: Path
    ) -> None:
        _add_supervisor(proc)
        rendered = _render(SupervisorIndicatorHandler(), missing_status, _SESSION_B)
        assert _BG_GREEN not in rendered
        assert rendered == ""

    def test_supervisor_owning_the_session_is_green(self, proc: Path, missing_status: Path) -> None:
        _add_supervisor(proc)
        assert _BG_GREEN in _render(SupervisorIndicatorHandler(), missing_status, _SESSION_A)

    def test_two_sessions_on_one_instance_are_independent(
        self, proc: Path, missing_status: Path
    ) -> None:
        _add_supervisor(proc)
        handler = SupervisorIndicatorHandler()
        assert _BG_GREEN in _render(handler, missing_status, _SESSION_A)
        assert _BG_GREEN not in _render(handler, missing_status, _SESSION_B)
        assert _BG_GREEN in _render(handler, missing_status, _SESSION_A)

    def test_other_session_first_does_not_poison_the_owner(
        self, proc: Path, missing_status: Path
    ) -> None:
        _add_supervisor(proc)
        handler = SupervisorIndicatorHandler()
        assert _BG_GREEN not in _render(handler, missing_status, _SESSION_B)
        assert _BG_GREEN in _render(handler, missing_status, _SESSION_A)

    def test_unreadable_environ_is_not_green(self, proc: Path, missing_status: Path) -> None:
        add_proc(proc, _SUPERVISOR_PID, 1, environ_unreadable=True)
        (proc / str(_SUPERVISOR_PID) / "cmdline").write_bytes(b"claude-supervise.py\x00--arm\x00")
        add_proc(proc, _CLAUDE_PID, _SUPERVISOR_PID, environ_unreadable=True)
        assert _render(SupervisorIndicatorHandler(), missing_status, _SESSION_A) == ""

    def test_no_session_id_is_not_green(self, proc: Path, missing_status: Path) -> None:
        _add_supervisor(proc)
        assert _render(SupervisorIndicatorHandler(), missing_status, {}) == ""

    def test_blank_or_non_string_session_id_is_not_green(
        self, proc: Path, missing_status: Path
    ) -> None:
        _add_supervisor(proc)
        handler = SupervisorIndicatorHandler()
        assert _render(handler, missing_status, {"session_id": ""}) == ""
        bad: dict[str, object] = {"session_id": 7}
        with patch(f"{_HANDLER}._status_file_path", return_value=missing_status):
            assert handler.handle(bad).context == []


class TestStatusFilePidIsHeldToTheSameRule:
    def test_status_file_pid_of_another_sessions_supervisor_is_orange_not_green(
        self, proc: Path, status_file: Path
    ) -> None:
        _add_supervisor(proc)
        rendered = _render(SupervisorIndicatorHandler(), status_file, _SESSION_B)
        assert _BG_GREEN not in rendered
        assert _BG_ORANGE in rendered

    def test_status_file_pid_owning_the_session_is_green(
        self, proc: Path, status_file: Path
    ) -> None:
        _add_supervisor(proc)
        assert _BG_GREEN in _render(SupervisorIndicatorHandler(), status_file, _SESSION_A)

    def test_status_file_without_session_id_is_orange(self, proc: Path, status_file: Path) -> None:
        _add_supervisor(proc)
        assert _BG_ORANGE in _render(SupervisorIndicatorHandler(), status_file, {})

    def test_status_file_sessions_are_independent_on_one_instance(
        self, proc: Path, status_file: Path
    ) -> None:
        _add_supervisor(proc)
        handler = SupervisorIndicatorHandler()
        assert _BG_GREEN in _render(handler, status_file, _SESSION_A)
        assert _BG_ORANGE in _render(handler, status_file, _SESSION_B)
        assert _BG_GREEN in _render(handler, status_file, _SESSION_A)


class TestPerSessionMemo:
    def test_memo_is_bounded(self, proc: Path, missing_status: Path) -> None:
        handler = SupervisorIndicatorHandler()
        for index in range(_MAX_TRACKED_SESSIONS + 5):
            _render(handler, missing_status, {"session_id": f"fake-session-{index}"})
        assert len(handler._memos) <= _MAX_TRACKED_SESSIONS

    def test_cached_supervisor_death_drops_only_that_sessions_memo(
        self, proc: Path, missing_status: Path
    ) -> None:
        _add_supervisor(proc)
        handler = SupervisorIndicatorHandler()
        assert _BG_GREEN in _render(handler, missing_status, _SESSION_A)
        shutil.rmtree(proc / str(_SUPERVISOR_PID))
        shutil.rmtree(proc / str(_CLAUDE_PID))
        with patch(f"{_MODULE}.os.kill", side_effect=ProcessLookupError):
            assert _BG_GREEN not in _render(handler, missing_status, _SESSION_A)
