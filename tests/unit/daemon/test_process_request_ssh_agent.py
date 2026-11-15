"""``_process_request`` binds the executor thread to the connecting hook process.

A handler that runs a remote git call reads the forwarded agent socket through
``ssh_agent.forwarded_agent_socket``; that only works when the dispatch thread
runs inside ``call_bound_to_peer`` for the kernel-stamped peer pid.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import DaemonConfig
from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.daemon.server import HooksDaemon
from claude_code_hooks_daemon.utils import ssh_agent

_SOCKET = "/run/session-agent.sock"


class _SocketProbe(Handler):
    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.TEST_SERVER, priority=Priority.TEST_HANDLER, terminal=True
        )
        self.seen: list[str | None] = []

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        self.seen.append(ssh_agent.forwarded_agent_socket())
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> _SocketProbe:
    monkeypatch.setattr(ssh_agent, "process_environ", lambda pid: ({"SSH_AUTH_SOCK": _SOCKET}, None))
    monkeypatch.setattr(ssh_agent, "validated_agent_socket", lambda value: value)
    return _SocketProbe()


def _daemon(probe: _SocketProbe) -> HooksDaemon:
    controller = FrontController(event_name="Stop")
    controller.register(probe)
    return HooksDaemon(config=_minimal_config(), controller=controller)


def _minimal_config() -> DaemonConfig:
    from tests.unit.daemon.test_event_socket_session_hostname import _config

    return _config(Path(tempfile.mkdtemp()))


class TestProcessRequestBindsThePeer:
    @pytest.mark.anyio
    async def test_a_handler_sees_the_forwarded_socket_of_the_connecting_process(
        self, probe: _SocketProbe
    ) -> None:
        request = json.dumps({"event": "Stop", "hook_input": {"hook_event_name": "Stop"}})
        await _daemon(probe)._process_request(request, peer=(4242, None))
        assert probe.seen == [_SOCKET]

    @pytest.mark.anyio
    async def test_a_request_without_a_peer_pid_sees_no_socket(self, probe: _SocketProbe) -> None:
        request = json.dumps({"event": "Stop", "hook_input": {"hook_event_name": "Stop"}})
        await _daemon(probe)._process_request(request)
        assert probe.seen == [None]
