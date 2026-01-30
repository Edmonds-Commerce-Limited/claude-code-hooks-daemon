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
from pathlib import Path
from unittest.mock import MagicMock, patch

from claude_code_hooks_daemon.daemon.cli import cmd_repair


class TestCmdRepair:
    """Tests for cmd_repair command."""

    def _make_args(self, tmp_path: Path) -> argparse.Namespace:
        """Create args namespace with project_root."""
        return argparse.Namespace(project_root=tmp_path)

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
