"""Plan 00628: the socket discovery file is published only after a successful bind.

The discovery file (``daemon-<host>.socket-path``) is SHARED by every start of a
project's daemon. The daemon child wrote it BEFORE binding and deleted it on any
crash. A start whose bind failed (a client seat: "AF_UNIX path too long")
therefore replaced a live incumbent's discovery file with its own unbindable
path and then removed it, so the next hook could no longer find the live
daemon while ``status`` reported it RUNNING.

Drives the real daemon-child branch of ``cmd_start`` with the real discovery
helpers; only the server's run is simulated.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_start
from claude_code_hooks_daemon.daemon.server import _SocketLiveness

_HOST = "discovery-fixture"


def _discovery_file(project: Path) -> Path:
    return project / ".claude" / "hooks-daemon" / "untracked" / f"daemon-{_HOST}.socket-path"


def _run_daemon_child(
    project: Path, run: Callable[[dict[str, Any]], None], monkeypatch: pytest.MonkeyPatch
) -> int:
    """Run ``cmd_start``'s daemon-child branch; ``run`` stands in for the server's run.

    ``run`` receives the keyword arguments ``HooksDaemon`` was built with, so
    it can call ``serving`` (the bind succeeded) or raise (it did not).
    """
    monkeypatch.setenv("HOSTNAME", _HOST)
    monkeypatch.delenv("CLAUDE_HOOKS_SOCKET_PATH", raising=False)
    monkeypatch.delenv("CLAUDE_HOOKS_PID_PATH", raising=False)
    (project / ".claude" / "hooks-daemon" / "untracked").mkdir(parents=True, exist_ok=True)
    sock_path = project / "d.sock"

    mock_config = MagicMock()
    mock_config.model_dump.return_value = {}
    mock_config.daemon.socket_path = str(sock_path)
    mock_config.daemon.pid_file_path = str(project / "d.pid")
    built: dict[str, Any] = {}

    def _build_daemon(*_args: Any, **kwargs: Any) -> MagicMock:
        built.update(kwargs)
        return MagicMock()

    def _asyncio_run(coro: Any) -> None:
        run(built)

    devnull = MagicMock()
    devnull.fileno.return_value = 99
    patchers = [
        patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=project),
        patch("claude_code_hooks_daemon.daemon.cli.get_socket_path", return_value=sock_path),
        patch("claude_code_hooks_daemon.daemon.cli.get_pid_path", return_value=project / "d.pid"),
        patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
        patch(
            "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
            return_value=_SocketLiveness.NOT_LIVE,
        ),
        patch("claude_code_hooks_daemon.daemon.cli.enforce_single_daemon"),
        patch("claude_code_hooks_daemon.daemon.cli.cleanup_stale_daemon_files", return_value=0),
        patch("claude_code_hooks_daemon.daemon.cli.write_cleanup_status"),
        patch("os.fork", side_effect=[0, 0]),
        patch("os.chdir"),
        patch("os.setsid"),
        patch("os.umask"),
        patch("os.dup2"),
        patch.object(sys, "stdin", MagicMock()),
        patch(
            "claude_code_hooks_daemon.config.models.Config.find_and_load",
            return_value=mock_config,
        ),
        patch(
            "claude_code_hooks_daemon.daemon.cli._build_initialised_controller",
            return_value=MagicMock(),
        ),
        patch("claude_code_hooks_daemon.daemon.server.HooksDaemon", side_effect=_build_daemon),
        patch("asyncio.run", side_effect=_asyncio_run),
    ]
    with ExitStack() as stack:
        for patcher in patchers:
            stack.enter_context(patcher)
        with pytest.raises(SystemExit) as exc_info:
            cmd_start(argparse.Namespace(project_root=project))
    code = exc_info.value.code
    assert isinstance(code, int)
    return code


def test_a_failed_bind_publishes_no_discovery_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _bind_fails(_built: dict[str, Any]) -> None:
        raise OSError("AF_UNIX path too long")

    assert _run_daemon_child(tmp_path, _bind_fails, monkeypatch) == 1
    assert not _discovery_file(tmp_path).exists()


def test_a_failed_bind_leaves_a_live_incumbents_discovery_file_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incumbent = "/run/user/1000/hooks-daemon-cafef00d-abc123.sock"
    _discovery_file(tmp_path).parent.mkdir(parents=True)
    _discovery_file(tmp_path).write_text(incumbent)

    def _bind_fails(_built: dict[str, Any]) -> None:
        raise OSError("AF_UNIX path too long")

    assert _run_daemon_child(tmp_path, _bind_fails, monkeypatch) == 1
    assert _discovery_file(tmp_path).read_text() == incumbent


def test_the_discovery_file_appears_only_once_the_socket_is_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, bool] = {}

    def _binds_then_stops(built: dict[str, Any]) -> None:
        seen["before_bind"] = _discovery_file(tmp_path).exists()
        built["serving"]()
        seen["after_bind"] = _discovery_file(tmp_path).exists()
        seen["content"] = _discovery_file(tmp_path).read_text() == str(tmp_path / "d.sock")

    assert _run_daemon_child(tmp_path, _binds_then_stops, monkeypatch) == 0
    assert seen == {"before_bind": False, "after_bind": True, "content": True}
    assert not _discovery_file(tmp_path).exists(), "the owner clears its own file on shutdown"


def test_a_crash_after_binding_clears_the_file_it_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _binds_then_crashes(built: dict[str, Any]) -> None:
        built["serving"]()
        raise RuntimeError("crashed while serving")

    assert _run_daemon_child(tmp_path, _binds_then_crashes, monkeypatch) == 1
    assert not _discovery_file(tmp_path).exists()
