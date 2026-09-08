"""Tests for cmd_repair CLI command.

Covers:
- Successful venv repair via uv sync
- uv not found error
- uv sync failure
- uv sync timeout
- Verification failure after repair
- Stops running daemon before repair
"""

import argparse
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.cli import (
    _UV_SYNC_TIMEOUT_SECONDS,
    _VERIFY_IMPORT_TIMEOUT_SECONDS,
    cmd_repair,
)
from claude_code_hooks_daemon.daemon.venv_lock import VenvLockTimeout


class TestCmdRepair:
    """Tests for cmd_repair command."""

    def _make_args(self, tmp_path: Path) -> argparse.Namespace:
        """Create args namespace with project_root."""
        return argparse.Namespace(project_root=tmp_path)

    def test_uv_sync_timeout_is_in_seconds_not_milliseconds(self, tmp_path: Path) -> None:
        """The timeout handed to subprocess.run must be SECONDS, not the
        millisecond BASH_DEFAULT constant.

        Regression: cmd_repair passed Timeout.BASH_DEFAULT (=120_000 ms)
        straight into subprocess.run(timeout=...), whose unit is SECONDS, so
        ``uv sync`` effectively never timed out (~33 hours).
        """
        args = self._make_args(tmp_path)

        mock_sync = MagicMock()
        mock_sync.returncode = 0
        mock_sync.stderr = ""

        mock_verify = MagicMock()
        mock_verify.returncode = 0
        mock_verify.stdout = "OK\n"

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=[mock_sync, mock_verify]) as mock_run,
        ):
            result = cmd_repair(args)

        assert result == 0
        sync_call = mock_run.call_args_list[0]
        passed_timeout = sync_call.kwargs["timeout"]
        # Must be the named seconds constant, NOT the millisecond BASH_DEFAULT.
        assert passed_timeout == _UV_SYNC_TIMEOUT_SECONDS
        assert passed_timeout == Timeout.BASH_DEFAULT // 1000
        assert passed_timeout != Timeout.BASH_DEFAULT

    def test_verification_subprocess_has_explicit_timeout(self, tmp_path: Path) -> None:
        """Finding #35: the post-repair import verification subprocess must be
        bounded by an explicit timeout (seconds), like the ``uv sync`` call.

        Without it, an interpreter that hangs on import made ``repair`` hang
        forever with no recovery.
        """
        args = self._make_args(tmp_path)

        mock_sync = MagicMock()
        mock_sync.returncode = 0
        mock_sync.stderr = ""

        mock_verify = MagicMock()
        mock_verify.returncode = 0
        mock_verify.stdout = "OK\n"

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=[mock_sync, mock_verify]) as mock_run,
        ):
            result = cmd_repair(args)

        assert result == 0
        verify_call = mock_run.call_args_list[1]
        assert verify_call.kwargs["timeout"] == _VERIFY_IMPORT_TIMEOUT_SECONDS
        assert _VERIFY_IMPORT_TIMEOUT_SECONDS > 0

    def test_verification_timeout_returns_failure(self, tmp_path: Path) -> None:
        """Finding #35: a hung verification import (TimeoutExpired) is a repair
        failure, returning 1 rather than crashing with an uncaught exception.
        """
        args = self._make_args(tmp_path)

        mock_sync = MagicMock()
        mock_sync.returncode = 0
        mock_sync.stderr = ""

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch(
                "subprocess.run",
                side_effect=[
                    mock_sync,
                    subprocess.TimeoutExpired("python", _VERIFY_IMPORT_TIMEOUT_SECONDS),
                ],
            ),
        ):
            result = cmd_repair(args)

        assert result == 1

    def test_successful_repair(self, tmp_path: Path) -> None:
        """cmd_repair returns 0 on successful uv sync + verification."""
        args = self._make_args(tmp_path)

        mock_sync = MagicMock()
        mock_sync.returncode = 0
        mock_sync.stderr = ""

        mock_verify = MagicMock()
        mock_verify.returncode = 0
        mock_verify.stdout = "OK\n"

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=[mock_sync, mock_verify]),
        ):
            result = cmd_repair(args)
            assert result == 0

    def test_uv_not_found(self, tmp_path: Path) -> None:
        """cmd_repair returns 1 when uv is not installed."""
        args = self._make_args(tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError("uv")),
        ):
            result = cmd_repair(args)
            assert result == 1

    def test_uv_sync_failure(self, tmp_path: Path) -> None:
        """cmd_repair returns 1 when uv sync fails."""
        args = self._make_args(tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error: could not resolve dependencies"

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = cmd_repair(args)
            assert result == 1

    def test_uv_sync_timeout(self, tmp_path: Path) -> None:
        """cmd_repair returns 1 when uv sync times out."""
        args = self._make_args(tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("uv", 120)),
        ):
            result = cmd_repair(args)
            assert result == 1

    def test_verification_failure(self, tmp_path: Path) -> None:
        """cmd_repair returns 1 when import verification fails after sync."""
        args = self._make_args(tmp_path)

        mock_sync = MagicMock()
        mock_sync.returncode = 0
        mock_sync.stderr = ""

        mock_verify = MagicMock()
        mock_verify.returncode = 1
        mock_verify.stderr = "ModuleNotFoundError: No module named 'claude_code_hooks_daemon'"

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=[mock_sync, mock_verify]),
        ):
            result = cmd_repair(args)
            assert result == 1

    def test_uv_sync_runs_under_the_venv_build_lock(self, tmp_path: Path) -> None:
        """Plan 00100 Task 4.3: repair contends on the same lock as ensure_venv.

        The ``uv sync`` must run INSIDE the lock's context — a lock taken and
        released around nothing would satisfy a call-count assertion and
        protect nothing.
        """
        args = self._make_args(tmp_path)
        events: list[str] = []

        @contextmanager
        def fake_lock(project_root: Path, **_kwargs: object) -> Iterator[None]:
            assert project_root == tmp_path
            events.append("lock")
            yield
            events.append("unlock")

        def fake_run(*_a: object, **_k: object) -> MagicMock:
            events.append("uv sync" if not events.count("uv sync") else "verify")
            done = MagicMock()
            done.returncode = 0
            done.stderr = ""
            done.stdout = "OK\n"
            return done

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("claude_code_hooks_daemon.daemon.cli.venv_lock", fake_lock),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = cmd_repair(args)

        assert result == 0
        assert events[0] == "lock" and events[-1] == "unlock", events
        assert "uv sync" in events[1:-1], f"uv sync must run inside the lock: {events}"

    def test_lock_timeout_is_reported_not_raised(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A held lock past the bound is a clear failure exit, not a traceback."""
        args = self._make_args(tmp_path)

        @contextmanager
        def held_lock(_project_root: Path, **_kwargs: object) -> Iterator[None]:
            raise VenvLockTimeout("gave up waiting for the venv lock after 120s: /x/lock")
            yield

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("claude_code_hooks_daemon.daemon.cli.venv_lock", held_lock),
            patch("subprocess.run") as mock_run,
        ):
            result = cmd_repair(args)

        assert result == 1
        mock_run.assert_not_called()
        assert "gave up waiting for the venv lock" in capsys.readouterr().out

    def test_stops_daemon_before_repair(self, tmp_path: Path) -> None:
        """cmd_repair stops running daemon before repairing."""
        args = self._make_args(tmp_path)

        mock_sync = MagicMock()
        mock_sync.returncode = 0
        mock_sync.stderr = ""

        mock_verify = MagicMock()
        mock_verify.returncode = 0
        mock_verify.stdout = "OK\n"

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_stop") as mock_stop,
            patch("subprocess.run", side_effect=[mock_sync, mock_verify]),
            patch("time.sleep"),
        ):
            result = cmd_repair(args)
            assert result == 0
            mock_stop.assert_called_once_with(args)
