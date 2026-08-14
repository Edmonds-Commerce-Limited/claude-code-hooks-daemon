"""Regression tests for the umask applied by the daemonise path (Plan 00239).

``daemon/cli.py`` daemonises with the textbook Stevens sequence
(``chdir("/")`` / ``setsid()`` / ``umask(...)``). The published recipe clears the
mask, which is safe ONLY for a daemon that passes an explicit mode to every
create — and this one does that at exactly one of 98 create sites. The running
daemon therefore produced ``0666`` files and ``0777`` directories throughout its
untracked tree, including the verdict log and ``payload-capture/``.

These tests cover the CALL. What the mask value actually does to a file on disk
is covered by ``tests/unit/constants/test_permissions.py``, next to the constant
itself.

Note what let the defect through: ``test_cli_cmd_start.py`` and
``test_cli_start_reuse.py`` already drive this exact line, and all six of their
daemonise tests ``patch("os.umask")`` without asserting anything about it. The
line was executed by the suite and unobserved by it.
"""

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants.permissions import FileMode
from claude_code_hooks_daemon.daemon.cli import cmd_start
from claude_code_hooks_daemon.daemon.server import _SocketLiveness


def _daemonise_to_first_child(tmp_path: Path) -> argparse.Namespace:
    """Build args for a ``cmd_start`` run that stops in the first child."""
    return argparse.Namespace(project_root=tmp_path)


class TestDaemoniseAppliesRestrictiveUmask:
    """The daemonise path must not hand the process a permissive mask."""

    @staticmethod
    def _run_first_child(tmp_path: Path) -> MagicMock:
        """Run ``cmd_start`` far enough to execute the umask call.

        The first fork returns 0 (we are the child) and the second returns a pid
        (we are the parent), so the child branch exits via ``SystemExit`` before
        any server startup happens.
        """
        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
            patch("os.fork", side_effect=[0, 200]),
            patch("os.chdir"),
            patch("os.setsid"),
            patch("os.umask") as mock_umask,
        ):
            with pytest.raises(SystemExit):
                cmd_start(_daemonise_to_first_child(tmp_path))
            return mock_umask

    def test_daemonise_sets_the_restrictive_mask(self, tmp_path: Path) -> None:
        """The first child applies ``FileMode.DAEMON_UMASK``."""
        mock_umask = self._run_first_child(tmp_path)

        mock_umask.assert_called_once_with(FileMode.DAEMON_UMASK)

    def test_daemonise_never_clears_the_mask(self, tmp_path: Path) -> None:
        """``os.umask(0)`` specifically must not be what the daemon applies.

        Asserted separately from the constant so a regression names the actual
        historical defect rather than reading as a constant mismatch.
        """
        mock_umask = self._run_first_child(tmp_path)

        applied = mock_umask.call_args.args[0]
        assert applied != 0, "daemonise cleared the umask — every create becomes 0666/0777"
