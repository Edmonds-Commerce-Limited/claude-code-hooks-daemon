"""SessionStart says plainly, once, when autonomy is off (Plan 00498 Task 2.3).

The gated handlers are silent where autonomy is off, so without this nothing tells
the session (or its owner) that the quiet is deliberate. The notice itself is
protective, not work-driving: it is never gated.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.support.autonomy import (
    CONTAINERS_ONLY,
    pin_autonomy,
    pin_container_containers_only,
    pin_desktop_containers_only,
)

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.handlers.session_start.autonomy_notice import AutonomyNoticeHandler

_EVENT: dict[str, Any] = {"hook_event_name": "SessionStart", "session_id": "s1"}


def _run(handler: AutonomyNoticeHandler) -> Any:
    chain = HandlerChain()
    chain.add(handler)
    return chain.execute(dict(_EVENT)).result


class TestIdentity:
    def test_it_is_a_non_terminal_advisory_that_does_not_drive_work(self) -> None:
        handler = AutonomyNoticeHandler()
        assert handler.handler_id == HandlerID.AUTONOMY_NOTICE
        assert handler.priority == Priority.AUTONOMY_NOTICE
        assert handler.terminal is False
        assert handler.drives_autonomy is False


class TestWhereAutonomyIsOff:
    def test_it_says_so_plainly_with_the_environment_and_the_remedy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_desktop_containers_only(monkeypatch)
        result = _run(AutonomyNoticeHandler())
        assert result.decision is Decision.ALLOW
        text = "\n".join(result.context)
        assert "AUTONOMY OFF" in text
        assert "'host'" in text
        assert "autonomy.environments" in text
        assert "Do only what you were asked" in text

    def test_it_speaks_once_not_once_per_line_of_advice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_desktop_containers_only(monkeypatch)
        result = _run(AutonomyNoticeHandler())
        assert sum("AUTONOMY OFF" in line for line in result.context) == 1


class TestWhereAutonomyIsOn:
    def test_it_is_silent_in_a_listed_container(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pin_container_containers_only(monkeypatch)
        assert _run(AutonomyNoticeHandler()).context == []

    def test_it_is_silent_when_the_project_declares_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_autonomy(monkeypatch, runtime=None)
        assert _run(AutonomyNoticeHandler()).context == []

    def test_a_role_alias_that_allows_autonomy_silences_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_autonomy(
            monkeypatch,
            runtime=None,
            autonomy_config=CONTAINERS_ONLY.model_copy(update={"hosts": ["cchd-sdlc-runner"]}),
        )
        monkeypatch.setenv("HOOKS_DAEMON_HOSTNAME", "cchd-sdlc-runner")
        assert _run(AutonomyNoticeHandler()).context == []
