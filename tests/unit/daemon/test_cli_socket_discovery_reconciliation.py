"""Tests for CLI split-brain socket reconciliation (Plan 00187).

A stale, git-tracked ``.claude/hooks-daemon.env`` can pin a non-canonical
socket name (an AF_UNIX length-limit workaround). ``init.sh`` sources that env
and binds/looks-up that name, while the Python management CLI — invoked without
the env — computes the deterministic hash name and reports ``NOT RUNNING``
even though a daemon is live. These tests cover ``_resolve_effective_daemon``,
which mirrors ``init.sh``'s socket-discovery-file fallback so ``status`` /
``health`` find the live daemon and emit a split-brain drift warning.
"""

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon.cli import _resolve_effective_daemon


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: Any) -> None:
    """Remove env var overrides so each test starts from a clean baseline."""
    monkeypatch.delenv("CLAUDE_HOOKS_SOCKET_PATH", raising=False)
    monkeypatch.delenv("CLAUDE_HOOKS_PID_PATH", raising=False)


def _args(**kw: Any) -> argparse.Namespace:
    kw.setdefault("project_root", None)
    kw.setdefault("socket", None)
    kw.setdefault("pid_file", None)
    return argparse.Namespace(**kw)


class TestResolveEffectiveDaemon:
    """_resolve_effective_daemon adopts the discovered live socket on drift."""

    def test_primary_live_returns_computed_no_warning(self, tmp_path: Path) -> None:
        """When the computed pid path is a live daemon, no fallback and no warning."""
        computed_sock = tmp_path / "daemon.sock"
        computed_pid = tmp_path / "daemon.pid"
        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=computed_sock,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_pid_path",
                return_value=computed_pid,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=4242,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_socket_discovery_file"
            ) as mock_disc,
        ):
            sock, pid, warning = _resolve_effective_daemon(_args(), tmp_path)

        assert sock == computed_sock
        assert pid == computed_pid
        assert warning is None
        # No need to consult discovery when the primary is already live.
        mock_disc.assert_not_called()

    def test_split_brain_adopts_discovered_socket_with_warning(self, tmp_path: Path) -> None:
        """Primary dead + discovery names a DIFFERENT live daemon → adopt + warn."""
        computed_sock = tmp_path / "hooks-daemon-aee977c2.sock"
        computed_pid = tmp_path / "hooks-daemon-aee977c2.pid"
        discovered_sock = tmp_path / "hooks-daemon-pda.sock"
        discovered_pid = tmp_path / "hooks-daemon-pda.pid"

        def _rpf(path: str, verify_daemon: bool = False) -> int | None:
            # Primary pid is dead; discovered pid is a live daemon.
            return 9999 if path == str(discovered_pid) else None

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=computed_sock,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_pid_path",
                return_value=computed_pid,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                side_effect=_rpf,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_socket_discovery_file",
                return_value=discovered_sock,
            ),
        ):
            sock, pid, warning = _resolve_effective_daemon(_args(), tmp_path)

        assert sock == discovered_sock
        assert pid == discovered_pid
        assert warning is not None
        # Warning must name BOTH paths so the operator can reconcile.
        assert str(discovered_sock) in warning
        assert str(computed_sock) in warning

    def test_discovery_names_same_path_no_warning(self, tmp_path: Path) -> None:
        """Discovery file naming the SAME computed path is not a split-brain."""
        computed_sock = tmp_path / "daemon.sock"
        computed_pid = tmp_path / "daemon.pid"
        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=computed_sock,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_pid_path",
                return_value=computed_pid,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_socket_discovery_file",
                return_value=computed_sock,
            ),
        ):
            sock, pid, warning = _resolve_effective_daemon(_args(), tmp_path)

        assert sock == computed_sock
        assert pid == computed_pid
        assert warning is None

    def test_discovered_daemon_dead_is_not_adopted(self, tmp_path: Path) -> None:
        """A stale discovery file (its daemon dead) must NOT be adopted."""
        computed_sock = tmp_path / "hooks-daemon-aee977c2.sock"
        computed_pid = tmp_path / "hooks-daemon-aee977c2.pid"
        discovered_sock = tmp_path / "hooks-daemon-pda.sock"
        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=computed_sock,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_pid_path",
                return_value=computed_pid,
            ),
            # Every pid path is dead (primary and discovered).
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_socket_discovery_file",
                return_value=discovered_sock,
            ),
        ):
            sock, pid, warning = _resolve_effective_daemon(_args(), tmp_path)

        assert sock == computed_sock
        assert pid == computed_pid
        assert warning is None

    def test_no_discovery_file_returns_computed(self, tmp_path: Path) -> None:
        """No discovery file → computed paths, no warning."""
        computed_sock = tmp_path / "daemon.sock"
        computed_pid = tmp_path / "daemon.pid"
        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=computed_sock,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_pid_path",
                return_value=computed_pid,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_socket_discovery_file",
                return_value=None,
            ),
        ):
            sock, pid, warning = _resolve_effective_daemon(_args(), tmp_path)

        assert sock == computed_sock
        assert pid == computed_pid
        assert warning is None

    def test_explicit_socket_flag_never_adopts_discovery(self, tmp_path: Path) -> None:
        """An explicit --socket flag is honoured verbatim — no discovery fallback."""
        flag_sock = tmp_path / "flag.sock"
        flag_pid = tmp_path / "flag.pid"
        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_socket_discovery_file"
            ) as mock_disc,
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file"
            ) as mock_rpf,
        ):
            sock, pid, warning = _resolve_effective_daemon(
                _args(socket=flag_sock, pid_file=flag_pid), tmp_path
            )

        assert sock == flag_sock
        assert pid == flag_pid
        assert warning is None
        mock_disc.assert_not_called()
        mock_rpf.assert_not_called()

    def test_explicit_env_override_never_adopts_discovery(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """A set CLAUDE_HOOKS_SOCKET_PATH is honoured verbatim — no discovery fallback."""
        env_sock = tmp_path / "env.sock"
        env_pid = tmp_path / "env.pid"
        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(env_sock))
        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=env_sock,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_pid_path",
                return_value=env_pid,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_socket_discovery_file"
            ) as mock_disc,
        ):
            sock, pid, warning = _resolve_effective_daemon(_args(), tmp_path)

        assert sock == env_sock
        assert pid == env_pid
        assert warning is None
        mock_disc.assert_not_called()


class TestCmdStatusSplitBrain:
    """cmd_status finds the live daemon via discovery and warns (Plan 00187)."""

    def test_status_reports_running_and_warns_on_split_brain(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        """Computed path dead + live daemon on discovered socket → RUNNING + warning."""
        from claude_code_hooks_daemon.daemon.cli import cmd_status

        computed_sock = tmp_path / "hooks-daemon-aee977c2.sock"
        computed_pid = tmp_path / "hooks-daemon-aee977c2.pid"
        discovered_sock = tmp_path / "hooks-daemon-pda.sock"
        discovered_pid = tmp_path / "hooks-daemon-pda.pid"
        discovered_sock.touch()  # a live socket file exists

        def _rpf(path: str, verify_daemon: bool = False) -> int | None:
            return 26257 if path == str(discovered_pid) else None

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=computed_sock,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_pid_path",
                return_value=computed_pid,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_socket_discovery_file",
                return_value=discovered_sock,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                side_effect=_rpf,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli._read_project_handler_health"
            ) as mock_health,
        ):
            mock_health.return_value.is_degraded = False
            result = cmd_status(_args())

        captured = capsys.readouterr()
        assert result == 0
        assert "RUNNING" in captured.out
        assert "PID: 26257" in captured.out
        # Drift warning goes to stderr and names both sockets.
        assert "split-brain" in captured.err
        assert str(discovered_sock) in captured.err
        assert str(computed_sock) in captured.err

    def test_status_not_running_when_no_live_daemon_anywhere(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        """No live daemon at computed or discovered path → NOT RUNNING, no warning."""
        from claude_code_hooks_daemon.daemon.cli import cmd_status

        computed_sock = tmp_path / "daemon.sock"
        computed_pid = tmp_path / "daemon.pid"
        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=computed_sock,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_pid_path",
                return_value=computed_pid,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_socket_discovery_file",
                return_value=None,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
        ):
            result = cmd_status(_args())

        captured = capsys.readouterr()
        assert result == 1
        assert "NOT RUNNING" in captured.out
        assert "split-brain" not in captured.err


class TestCmdHealthSplitBrain:
    """cmd_health finds the live daemon via discovery and warns (Plan 00187)."""

    def test_health_queries_discovered_socket_and_warns(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        """Health talks to the discovered live daemon and emits the drift warning."""
        from claude_code_hooks_daemon.daemon.cli import cmd_health

        computed_sock = tmp_path / "hooks-daemon-aee977c2.sock"
        computed_pid = tmp_path / "hooks-daemon-aee977c2.pid"
        discovered_sock = tmp_path / "hooks-daemon-pda.sock"
        discovered_pid = tmp_path / "hooks-daemon-pda.pid"

        def _rpf(path: str, verify_daemon: bool = False) -> int | None:
            return 26257 if path == str(discovered_pid) else None

        health_response = {
            "result": {
                "status": "healthy",
                "stats": {},
                "handlers": {"PreToolUse": 37},
            }
        }

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=computed_sock,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_pid_path",
                return_value=computed_pid,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_socket_discovery_file",
                return_value=discovered_sock,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                side_effect=_rpf,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=health_response,
            ) as mock_send,
            patch(
                "claude_code_hooks_daemon.daemon.cli.check_hook_registration_warnings",
                return_value=[],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli._read_project_handler_health"
            ) as mock_health,
            patch(
                "claude_code_hooks_daemon.daemon.cli._format_project_handler_health_lines",
                return_value=[],
            ),
        ):
            mock_health.return_value.is_degraded = False
            result = cmd_health(_args())

        captured = capsys.readouterr()
        assert result == 0
        assert "HEALTHY" in captured.out
        # The health request must target the DISCOVERED (live) socket.
        assert mock_send.call_args[0][0] == discovered_sock
        assert "split-brain" in captured.err
