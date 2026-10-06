"""A work-driving handler is skipped before `matches()` where autonomy is off (Plan 00498).

Same seam, and same reasoning, as `Handler.scope` (Plan 00423): one gate in the
chain cannot be forgotten, where a per-handler check is one chance to forget per
handler. A handler that sets `drives_autonomy` is never consulted, so it adds no
context, no verdict and no decision. A handler that does not set it (every guard)
is untouched, whatever the environment.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from tests.support.autonomy import pin_container_containers_only, pin_desktop_containers_only


class _Recorder(Handler):
    """Matches everything and records that it was asked."""

    drives_autonomy: ClassVar[bool] = False

    def __init__(self, handler_id: str) -> None:
        super().__init__(handler_id=handler_id, priority=Priority.DEFAULT, terminal=False)
        self.matches_called = False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        self.matches_called = True
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW, context=[f"ran:{self.name}"])

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


class _Driver(_Recorder):
    drives_autonomy: ClassVar[bool] = True


class _Guard(_Recorder):
    drives_autonomy: ClassVar[bool] = False


_EVENT: dict[str, Any] = {"hook_event_name": "SessionStart", "session_id": "s1"}


def _run(*handlers: Handler) -> Any:
    chain = HandlerChain()
    for handler in handlers:
        chain.add(handler)
    return chain.execute(dict(_EVENT))


def test_the_default_is_a_guard_that_always_runs() -> None:
    assert Handler.drives_autonomy is False


def test_a_driver_is_skipped_where_autonomy_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_desktop_containers_only(monkeypatch)
    driver = _Driver("driver")
    result = _run(driver)
    assert driver.matches_called is False
    assert "ran:driver" not in result.result.context
    assert result.handlers_matched == []


def test_a_guard_still_runs_where_autonomy_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_desktop_containers_only(monkeypatch)
    guard = _Guard("guard")
    driver = _Driver("driver")
    result = _run(guard, driver)
    assert guard.matches_called is True
    assert "ran:guard" in result.result.context
    assert driver.matches_called is False


def test_a_driver_runs_unchanged_where_autonomy_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_container_containers_only(monkeypatch)
    driver = _Driver("driver")
    result = _run(driver)
    assert driver.matches_called is True
    assert "ran:driver" in result.result.context
