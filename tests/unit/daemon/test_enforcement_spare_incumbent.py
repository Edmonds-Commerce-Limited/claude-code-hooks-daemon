"""Plan 00127: enforce_single_daemon must spare the live owner of our socket.

Defence-in-depth backstop (Decision 1): even if enforcement runs, it must not
kill the healthy shared daemon that owns the socket this start will reuse. It
must still reap genuinely stale/orphaned peers.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from claude_code_hooks_daemon.daemon.enforcement import enforce_single_daemon


class TestEnforceSparesLiveSocketOwner:
    """The PID owning a LIVE socket must be excluded from the kill list."""

    def test_spares_live_socket_owner_kills_stale_peer(self, tmp_path: Path) -> None:
        """Container + enforcement on: the live-socket owner is spared; a
        genuinely orphaned peer is still killed."""
        socket_path = tmp_path / "daemon.sock"

        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        current_pid = os.getpid()
        incumbent_pid = current_pid + 1000  # owns the live socket — KEEP
        orphan_pid = current_pid + 2000  # stale/orphaned — KILL

        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=True,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                return_value=[current_pid, incumbent_pid, orphan_pid],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement._socket_is_live",
                return_value=True,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.read_pid_file",
                return_value=incumbent_pid,
            ),
            patch("claude_code_hooks_daemon.daemon.enforcement.kill_daemon_process") as mock_kill,
        ):
            enforce_single_daemon(
                config=mock_config,
                pid_path=tmp_path / "daemon.pid",
                project_root=tmp_path,
                socket_path=socket_path,
            )

        # Orphan killed, incumbent spared, current never targeted.
        mock_kill.assert_called_once_with(orphan_pid)

    def test_kills_all_peers_when_socket_dead(self, tmp_path: Path) -> None:
        """If the socket is NOT live, no incumbent to spare — all peers killed."""
        socket_path = tmp_path / "daemon.sock"

        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        current_pid = os.getpid()
        peer_1 = current_pid + 1000
        peer_2 = current_pid + 2000

        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=True,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                return_value=[current_pid, peer_1, peer_2],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement._socket_is_live",
                return_value=False,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.read_pid_file",
                return_value=None,
            ),
            patch("claude_code_hooks_daemon.daemon.enforcement.kill_daemon_process") as mock_kill,
        ):
            enforce_single_daemon(
                config=mock_config,
                pid_path=tmp_path / "daemon.pid",
                project_root=tmp_path,
                socket_path=socket_path,
            )

        assert mock_kill.call_count == 2
        mock_kill.assert_any_call(peer_1)
        mock_kill.assert_any_call(peer_2)
