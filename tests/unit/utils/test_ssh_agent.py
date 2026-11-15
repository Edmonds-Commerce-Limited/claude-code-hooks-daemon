"""The session's SSH agent socket, read per request from the connecting hook process.

A daemon started by an upgrade has no ``SSH_AUTH_SOCK``; the hook process on the
other end of the socket has the session's. Only that one variable is taken, only
when it names an absolute socket owned by the daemon's uid, and its value is
never logged.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.bounded_dispatch import BoundedDispatcher
from claude_code_hooks_daemon.utils import ssh_agent
from claude_code_hooks_daemon.utils.ssh_agent import (
    AgentSocketRejected,
    call_bound_to_peer,
    forwarded_agent_socket,
    validated_agent_socket,
)


@pytest.fixture
def agent_socket() -> Iterator[str]:
    """A real listening Unix socket under a short path (sun_path is ~108 bytes)."""
    with tempfile.TemporaryDirectory(prefix="agt") as directory:
        path = str(Path(directory) / "a.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        try:
            yield path
        finally:
            server.close()


class TestValidatedAgentSocket:
    def test_an_owned_absolute_socket_is_accepted(self, agent_socket: str) -> None:
        assert validated_agent_socket(agent_socket) == agent_socket

    @pytest.mark.parametrize("value", ["", "   "])
    def test_an_empty_value_is_rejected(self, value: str) -> None:
        with pytest.raises(AgentSocketRejected) as caught:
            validated_agent_socket(value)
        assert caught.value.reason == "empty"

    def test_a_relative_path_is_rejected(self, agent_socket: str) -> None:
        relative = os.path.relpath(agent_socket)
        with pytest.raises(AgentSocketRejected) as caught:
            validated_agent_socket(relative)
        assert caught.value.reason == "not absolute"

    def test_a_regular_file_is_rejected(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.write_text("x")
        with pytest.raises(AgentSocketRejected) as caught:
            validated_agent_socket(str(plain))
        assert caught.value.reason == "not a socket"

    def test_a_missing_path_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(AgentSocketRejected) as caught:
            validated_agent_socket(str(tmp_path / "gone.sock"))
        assert caught.value.reason == "unreadable"

    def test_a_path_with_a_nul_byte_is_rejected(self) -> None:
        with pytest.raises(AgentSocketRejected) as caught:
            validated_agent_socket("/tmp/a\0b")
        assert caught.value.reason == "unreadable"

    def test_a_socket_owned_by_another_uid_is_rejected(self, agent_socket: str) -> None:
        with pytest.raises(AgentSocketRejected) as caught:
            validated_agent_socket(agent_socket, uid=os.getuid() + 1)
        assert caught.value.reason == "not owned by the daemon user"

    def test_the_rejection_never_carries_the_value(self) -> None:
        with pytest.raises(AgentSocketRejected) as caught:
            validated_agent_socket("relative-secret.sock")
        assert "relative-secret.sock" not in str(caught.value)


class TestForwardedAgentSocket:
    def test_nothing_is_forwarded_when_no_request_is_bound(self) -> None:
        assert forwarded_agent_socket() is None

    def test_the_bound_peers_validated_socket_is_forwarded(
        self, monkeypatch: pytest.MonkeyPatch, agent_socket: str
    ) -> None:
        monkeypatch.setattr(
            ssh_agent, "process_environ", lambda pid: ({"SSH_AUTH_SOCK": agent_socket}, None)
        )
        assert call_bound_to_peer(4242, forwarded_agent_socket) == agent_socket

    def test_the_binding_ends_with_the_call(
        self, monkeypatch: pytest.MonkeyPatch, agent_socket: str
    ) -> None:
        monkeypatch.setattr(
            ssh_agent, "process_environ", lambda pid: ({"SSH_AUTH_SOCK": agent_socket}, None)
        )
        call_bound_to_peer(4242, forwarded_agent_socket)
        assert forwarded_agent_socket() is None

    def test_an_unreadable_peer_falls_back_silently(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(ssh_agent, "process_environ", lambda pid: (None, "gone"))
        with caplog.at_level(logging.DEBUG):
            assert call_bound_to_peer(4242, forwarded_agent_socket) is None
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    @pytest.mark.parametrize("pid", [None, 0, -1])
    def test_an_unknown_peer_pid_binds_nothing(
        self, monkeypatch: pytest.MonkeyPatch, pid: int | None
    ) -> None:
        def boom(_pid: int) -> tuple[dict[str, str] | None, str | None]:
            raise AssertionError("the environment must not be read")

        monkeypatch.setattr(ssh_agent, "process_environ", boom)
        assert call_bound_to_peer(pid, forwarded_agent_socket) is None

    def test_a_peer_without_the_variable_forwards_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ssh_agent, "process_environ", lambda pid: ({"HOME": "/h"}, None))
        assert call_bound_to_peer(4242, forwarded_agent_socket) is None

    def test_an_invalid_value_forwards_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            ssh_agent, "process_environ", lambda pid: ({"SSH_AUTH_SOCK": "relative.sock"}, None)
        )
        assert call_bound_to_peer(4242, forwarded_agent_socket) is None

    def test_an_invalid_value_is_recorded_by_reason_only(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(
            ssh_agent, "process_environ", lambda pid: ({"SSH_AUTH_SOCK": "relative.sock"}, None)
        )
        with caplog.at_level(logging.DEBUG):
            call_bound_to_peer(4242, forwarded_agent_socket)
        assert "not absolute" in caplog.text
        assert "relative.sock" not in caplog.text

    @pytest.mark.parametrize("value", ["", "   "])
    def test_an_empty_value_forwards_nothing(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setattr(
            ssh_agent, "process_environ", lambda pid: ({"SSH_AUTH_SOCK": value}, None)
        )
        assert call_bound_to_peer(4242, forwarded_agent_socket) is None

    def test_the_value_is_never_logged(
        self,
        monkeypatch: pytest.MonkeyPatch,
        agent_socket: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(
            ssh_agent, "process_environ", lambda pid: ({"SSH_AUTH_SOCK": agent_socket}, None)
        )
        with caplog.at_level(logging.DEBUG):
            call_bound_to_peer(4242, forwarded_agent_socket)
            monkeypatch.setattr(
                ssh_agent, "process_environ", lambda pid: ({"SSH_AUTH_SOCK": "/nope/x"}, None)
            )
            call_bound_to_peer(4242, forwarded_agent_socket)
        assert agent_socket not in caplog.text
        assert "/nope/x" not in caplog.text

    def test_a_real_peer_process_environment_is_read(self, agent_socket: str) -> None:
        peer = subprocess.Popen(
            [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(30)"],
            env={"SSH_AUTH_SOCK": agent_socket, "PATH": os.environ.get("PATH", "")},
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert peer.stdout is not None
            assert peer.stdout.readline().strip() == "up"  # exec has happened
            assert call_bound_to_peer(peer.pid, forwarded_agent_socket) == agent_socket
        finally:
            peer.kill()
            peer.wait()

    def test_the_binding_reaches_a_handler_thread_run_by_the_bounded_dispatcher(
        self, monkeypatch: pytest.MonkeyPatch, agent_socket: str
    ) -> None:
        monkeypatch.setattr(
            ssh_agent, "process_environ", lambda pid: ({"SSH_AUTH_SOCK": agent_socket}, None)
        )
        dispatcher = BoundedDispatcher(max_inflight=2)
        result = call_bound_to_peer(
            4242,
            lambda: dispatcher.run(
                forwarded_agent_socket,
                timeout=Timeout.SOCKET_DISPATCH_ROUNDTRIP,
                label="ssh-agent-test",
            ),
        )
        assert result == agent_socket
