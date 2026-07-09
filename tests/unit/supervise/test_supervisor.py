"""Tests for the standalone claude-supervise.py `supervise()` PTY loop.

These run the real `supervise()` function against real child processes on a
real PTY. Stdin is deliberately NOT a tty in this test process (pytest), which
exercises the `os.isatty()` guard around termios raw-mode handling.

Output is captured via pytest's `capfd` fixture, which captures at the file
descriptor level -- required here because `supervise()` writes directly to
`os.write(sys.stdout.fileno(), ...)` rather than through Python's `sys.stdout`
object.
"""

from __future__ import annotations

import errno
import os
import select
import signal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
DecisionLog = _mod.DecisionLog
InputActivity = _mod.InputActivity
supervise = _mod.supervise
_exit_code_from_status = _mod._exit_code_from_status
_forward_io = _mod._forward_io


def _supervise_with_default_stdin(
    argv: list[str],
    *,
    dry_run: bool = True,
    log: object | None = None,
    activity: object | None = None,
    stdin_fd: int | None = None,
) -> int:
    """Run supervise(argv), using a real /dev/null fd for stdin by default."""
    owned_stdin_fd: int | None = None
    if stdin_fd is None:
        owned_stdin_fd = os.open(os.devnull, os.O_RDONLY)
        stdin_fd = owned_stdin_fd
    try:
        return int(supervise(argv, dry_run=dry_run, log=log, activity=activity, stdin_fd=stdin_fd))
    finally:
        if owned_stdin_fd is not None:
            os.close(owned_stdin_fd)


class TestSuperviseOutputPassthrough:
    """The child's stdout must reach the supervisor's stdout unchanged."""

    def test_child_output_reaches_stdout(self, capfd: pytest.CaptureFixture[str]) -> None:
        code = _supervise_with_default_stdin(["bash", "-lc", "printf 'SUPERVISE_OUT\\n'; exit 0"])
        assert code == 0
        assert "SUPERVISE_OUT" in capfd.readouterr().out


class TestSuperviseExitCodePropagation:
    """Exit codes and signal deaths must propagate faithfully."""

    def test_exit_zero_propagates(self) -> None:
        code = _supervise_with_default_stdin(["bash", "-lc", "exit 0"])
        assert code == 0

    def test_nonzero_exit_propagates(self) -> None:
        code = _supervise_with_default_stdin(["bash", "-lc", "exit 42"])
        assert code == 42

    def test_signalled_child_propagates_128_plus_signal(self) -> None:
        code = _supervise_with_default_stdin(["bash", "-lc", "kill -TERM $$"])
        assert code == 143


class TestSuperviseInputAccounting:
    """Input bytes forwarded from stdin must be observed and counted."""

    def test_input_bytes_are_counted(self) -> None:
        activity = InputActivity()
        read_fd, write_fd = os.pipe()
        os.write(write_fd, b"hello")
        os.close(write_fd)

        try:
            code = _supervise_with_default_stdin(
                ["bash", "-lc", "read -N 5 _unused; exit 0"],
                activity=activity,
                stdin_fd=read_fd,
            )
        finally:
            os.close(read_fd)

        assert code == 0
        assert activity.bytes_seen == len(b"hello")
        assert activity.last_input_monotonic is not None


class TestSuperviseDecisionLogging:
    """v0 is transparent passthrough; dry_run only affects logging."""

    def test_startup_line_is_logged_before_child_runs(self, tmp_path: Path) -> None:
        log = DecisionLog(tmp_path / "decision.log")

        code = _supervise_with_default_stdin(
            ["bash", "-lc", "exit 0"],
            dry_run=True,
            log=log,
        )

        assert code == 0
        contents = log.path.read_text(encoding="utf-8")
        assert "supervisor active (dry-run)" in contents
        assert "transparent passthrough" in contents
        assert "wrapping:" in contents

    def test_exit_summary_logs_dry_run_and_byte_count(self, tmp_path: Path) -> None:
        log = DecisionLog(tmp_path / "decision.log")

        code = _supervise_with_default_stdin(
            ["bash", "-lc", "exit 0"],
            dry_run=True,
            log=log,
        )

        assert code == 0
        contents = log.path.read_text(encoding="utf-8")
        assert "supervisor exiting (dry-run)" in contents
        assert "input bytes observed" in contents

    def test_armed_mode_logs_armed_label(self, tmp_path: Path) -> None:
        log = DecisionLog(tmp_path / "decision.log")

        code = _supervise_with_default_stdin(
            ["bash", "-lc", "exit 0"],
            dry_run=False,
            log=log,
        )

        assert code == 0
        contents = log.path.read_text(encoding="utf-8")
        assert "armed (no-op in v0)" in contents

    def test_no_log_provided_does_not_raise(self) -> None:
        code = _supervise_with_default_stdin(["bash", "-lc", "exit 0"], log=None)
        assert code == 0


class TestSuperviseTermiosGuard:
    """When stdin is not a tty (e.g. under pytest), no termios calls are made."""

    def test_supervise_does_not_touch_termios_when_stdin_not_a_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        devnull_fd = os.open(os.devnull, os.O_RDONLY)
        tcgetattr_mock = MagicMock()
        tcsetattr_mock = MagicMock()
        monkeypatch.setattr(_mod.termios, "tcgetattr", tcgetattr_mock)
        monkeypatch.setattr(_mod.termios, "tcsetattr", tcsetattr_mock)
        try:
            assert os.isatty(devnull_fd) is False

            code = _supervise_with_default_stdin(["bash", "-lc", "exit 0"], stdin_fd=devnull_fd)
        finally:
            os.close(devnull_fd)

        assert code == 0
        tcgetattr_mock.assert_not_called()
        tcsetattr_mock.assert_not_called()


class TestSuperviseWinchForwarding:
    """SIGWINCH received during supervision must re-sync the pty window size."""

    def test_sigwinch_triggers_winsize_resync(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import threading

        set_winsize_mock = MagicMock()
        monkeypatch.setattr(_mod, "_set_winsize", set_winsize_mock)
        set_winsize_mock.reset_mock()  # clear the pre-fork call made by supervise() itself

        def _send_sigwinch_soon() -> None:
            os.kill(os.getpid(), signal.SIGWINCH)

        timer = threading.Timer(0.05, _send_sigwinch_soon)
        timer.start()
        try:
            code = _supervise_with_default_stdin(["bash", "-lc", "sleep 0.2; exit 0"])
        finally:
            timer.cancel()

        assert code == 0
        assert set_winsize_mock.call_count >= 1


class TestSuperviseTtyPath:
    """When stdin IS a tty, termios raw-mode is entered and restored."""

    def test_supervise_saves_and_restores_termios_for_a_real_tty(self) -> None:
        primary_fd, secondary_fd = os.openpty()
        try:
            code = _supervise_with_default_stdin(["bash", "-lc", "exit 0"], stdin_fd=secondary_fd)
        finally:
            os.close(primary_fd)
            os.close(secondary_fd)

        assert code == 0


class TestSuperviseEmptyArgv:
    """FAIL FAST: an empty argv is a programming error, not a runtime one."""

    def test_empty_argv_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="non-empty argv"):
            supervise([])


class TestExitCodeFromStatus:
    """Unit tests for the private waitpid-status translator."""

    def test_neither_exited_nor_signalled_falls_back_to_one(self) -> None:
        stopped_status = (signal.SIGSTOP << 8) | 0x7F
        assert _exit_code_from_status(stopped_status) == 1


class TestForwardIoSelectRetry:
    """Unit tests for the private select() loop helper."""

    def test_retries_on_eintr_then_stops_on_master_eof(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stdin_read_fd, stdin_write_fd = os.pipe()
        master_read_fd, master_write_fd = os.pipe()
        os.close(master_write_fd)  # immediate EOF on the "master" side

        real_select = select.select
        calls = {"count": 0}

        def _flaky_select(
            rlist: list[int], wlist: list[int], xlist: list[int]
        ) -> tuple[list[int], list[int], list[int]]:
            calls["count"] += 1
            if calls["count"] == 1:
                raise OSError(errno.EINTR, "interrupted")
            return real_select(rlist, wlist, xlist)

        monkeypatch.setattr(_mod.select, "select", _flaky_select)

        try:
            _forward_io(stdin_read_fd, master_read_fd, InputActivity())
        finally:
            os.close(stdin_read_fd)
            os.close(stdin_write_fd)
            os.close(master_read_fd)

        assert calls["count"] >= 2

    def test_reraises_non_eintr_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stdin_read_fd, stdin_write_fd = os.pipe()
        master_read_fd, master_write_fd = os.pipe()

        def _broken_select(
            rlist: list[int], wlist: list[int], xlist: list[int]
        ) -> tuple[list[int], list[int], list[int]]:
            raise OSError(errno.EIO, "broken")

        monkeypatch.setattr(_mod.select, "select", _broken_select)

        try:
            with pytest.raises(OSError, match="broken"):
                _forward_io(stdin_read_fd, master_read_fd, InputActivity())
        finally:
            os.close(stdin_read_fd)
            os.close(stdin_write_fd)
            os.close(master_read_fd)
            os.close(master_write_fd)

    def test_ignores_empty_stdin_read_then_stops_on_master_eof(self) -> None:
        stdin_read_fd, stdin_write_fd = os.pipe()
        os.close(stdin_write_fd)  # immediate EOF on the "stdin" side
        master_read_fd, master_write_fd = os.pipe()
        os.close(master_write_fd)  # immediate EOF on the "master" side

        activity = InputActivity()
        try:
            _forward_io(stdin_read_fd, master_read_fd, activity)
        finally:
            os.close(stdin_read_fd)
            os.close(master_read_fd)

        assert activity.bytes_seen == 0
