"""The session's teamchat signals reach the daemon over the byte-pump relay (Plan 00631 Task 2.2).

The role probe runs ``$TEAMCHAT_KIT/bin/teamchat whoami --json`` with the
SESSION's ``TEAMCHAT_RUNTIME``. The daemon's own environment is not the
session's, and the relay never parses the payload, so the daemon reads both
variables from the process on the other end of the per-event socket and stamps
them as ``teamchat_runtime`` / ``teamchat_kit``. The pair comes from ONE source
(review F7): a readable peer environment supplies both fields, replacing or
removing payload values; only when it is unreadable does the payload pair stand.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from tests.unit.daemon.test_event_socket_session_hostname import _run

from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.daemon import server

_RUNTIME = "/run/teamchat/a"
_KIT = "/opt/teamchat-kit"


def _environ_reader(
    environ: dict[str, str] | None, reason: str | None = None
) -> tuple[list[int], Any]:
    calls: list[int] = []

    def _read(pid: int) -> tuple[dict[str, str] | None, str | None]:
        calls.append(pid)
        return environ, reason

    return calls, _read


class TestStampTeamchatSignals:
    def test_both_signals_are_stamped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls, read = _environ_reader(
            {"TEAMCHAT_RUNTIME": _RUNTIME, "TEAMCHAT_KIT": _KIT, "SECRET_TOKEN": "x"}
        )
        monkeypatch.setattr(server, "process_environ", read)
        payload: dict[str, Any] = {"hook_event_name": "Stop"}

        server._stamp_teamchat_signals(payload, (4242, None))

        assert payload == {
            "hook_event_name": "Stop",
            HookInputField.TEAMCHAT_RUNTIME: _RUNTIME,
            HookInputField.TEAMCHAT_KIT: _KIT,
        }
        assert calls == [4242]

    def test_blank_values_stamp_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, read = _environ_reader({"TEAMCHAT_RUNTIME": "  ", "TEAMCHAT_KIT": ""})
        monkeypatch.setattr(server, "process_environ", read)
        payload: dict[str, Any] = {"hook_event_name": "Stop"}

        server._stamp_teamchat_signals(payload, (4242, None))

        assert payload == {"hook_event_name": "Stop"}

    def test_the_peer_environment_replaces_a_payload_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Review F7: the peer's environment is authoritative when readable."""
        _, read = _environ_reader({"TEAMCHAT_RUNTIME": "/peer", "TEAMCHAT_KIT": _KIT})
        monkeypatch.setattr(server, "process_environ", read)
        payload: dict[str, Any] = {HookInputField.TEAMCHAT_RUNTIME: "/from-transport"}

        server._stamp_teamchat_signals(payload, (4242, None))

        assert payload == {
            HookInputField.TEAMCHAT_RUNTIME: "/peer",
            HookInputField.TEAMCHAT_KIT: _KIT,
        }

    def test_the_pair_never_mixes_sources(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Review F7: a payload kit is never combined with the peer's runtime."""
        calls, read = _environ_reader({"TEAMCHAT_RUNTIME": "/peer"})
        monkeypatch.setattr(server, "process_environ", read)
        payload: dict[str, Any] = {
            HookInputField.TEAMCHAT_RUNTIME: "/a",
            HookInputField.TEAMCHAT_KIT: "/payload-kit",
        }

        server._stamp_teamchat_signals(payload, (4242, None))

        assert payload == {HookInputField.TEAMCHAT_RUNTIME: "/peer"}
        assert calls == [4242]

    def test_a_peer_outside_a_team_clears_payload_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, read = _environ_reader({"TEAMCHAT_RUNTIME": " "})
        monkeypatch.setattr(server, "process_environ", read)
        payload: dict[str, Any] = {
            "hook_event_name": "Stop",
            HookInputField.TEAMCHAT_RUNTIME: "/a",
            HookInputField.TEAMCHAT_KIT: "/b",
        }

        server._stamp_teamchat_signals(payload, (4242, None))

        assert payload == {"hook_event_name": "Stop"}

    def test_an_unreadable_peer_leaves_the_payload_pair(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, read = _environ_reader(None, "gone")
        monkeypatch.setattr(server, "process_environ", read)
        payload: dict[str, Any] = {
            HookInputField.TEAMCHAT_RUNTIME: "/a",
            HookInputField.TEAMCHAT_KIT: "/b",
        }

        server._stamp_teamchat_signals(payload, (4242, None))

        assert payload == {
            HookInputField.TEAMCHAT_RUNTIME: "/a",
            HookInputField.TEAMCHAT_KIT: "/b",
        }

    @pytest.mark.parametrize("peer", [(None, "no SO_PEERCRED"), (0, None), (-1, None)])
    def test_an_unknown_peer_reads_nothing(
        self, monkeypatch: pytest.MonkeyPatch, peer: tuple[int | None, str | None]
    ) -> None:
        calls, read = _environ_reader({"TEAMCHAT_RUNTIME": _RUNTIME})
        monkeypatch.setattr(server, "process_environ", read)
        payload: dict[str, Any] = {}

        server._stamp_teamchat_signals(payload, peer)

        assert payload == {}
        assert calls == []

    def test_an_unreadable_environment_stamps_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, read = _environ_reader(None, "gone")
        monkeypatch.setattr(server, "process_environ", read)
        payload: dict[str, Any] = {}

        server._stamp_teamchat_signals(payload, (4242, None))

        assert payload == {}

    def test_a_non_dict_payload_is_left_unchanged(self) -> None:
        payload = ["not", "a", "dict"]

        server._stamp_teamchat_signals(payload, (4242, None))

        assert payload == ["not", "a", "dict"]


@pytest.fixture
def untracked_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _client_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in {"TEAMCHAT_RUNTIME", "TEAMCHAT_KIT"}}
    env.update(extra)
    return env


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc/<pid>/environ")
class TestPeerTeamchatEnvironmentIsStamped:
    @pytest.mark.anyio
    async def test_the_clients_signals_are_stamped_not_the_daemons(
        self, untracked_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEAMCHAT_RUNTIME", "/daemon-own-env")
        seen = await _run(
            untracked_dir,
            {"hook_event_name": "Stop"},
            _client_env(TEAMCHAT_RUNTIME=_RUNTIME, TEAMCHAT_KIT=_KIT),
        )
        assert seen is not None
        assert seen[HookInputField.TEAMCHAT_RUNTIME] == _RUNTIME
        assert seen[HookInputField.TEAMCHAT_KIT] == _KIT

    @pytest.mark.anyio
    async def test_a_client_outside_a_team_stamps_nothing(
        self, untracked_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEAMCHAT_RUNTIME", "/daemon-own-env")
        seen = await _run(untracked_dir, {"hook_event_name": "Stop"}, _client_env())
        assert seen is not None
        assert HookInputField.TEAMCHAT_RUNTIME not in seen
        assert HookInputField.TEAMCHAT_KIT not in seen
