"""No ``.goal-intent`` is written while a session is focused (Plan 00501 Task 3.2, ruling 06).

``goal_injection`` is a ``drives_autonomy`` handler, so the chain's autonomy gate
skips it for a focused session before ``matches()`` is consulted: nothing it
does, including writing the goal signal, can happen. Driven through the real
chain and the real session-modes registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.support.autonomy import focus_entry, pin_container_containers_only, pin_session_modes

from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import GoalInjectionHandler

_SESSION = "sess-focus"


def _run(handler: GoalInjectionHandler) -> Any:
    chain = HandlerChain()
    chain.add(handler)
    return chain.execute(
        {"hook_event_name": "PostToolUse", "session_id": _SESSION, "tool_name": "Edit"}
    )


def _signal_writing_handle(tmp_path: Path) -> Any:
    def _handle(_self: GoalInjectionHandler, hook_input: dict[str, Any]) -> BlockingResult:
        (tmp_path / f"{_SESSION}.goal-intent").write_text("{}", encoding="utf-8")
        return BlockingResult(decision=Decision.ALLOW)

    return _handle


def test_goal_injection_drives_autonomy() -> None:
    assert GoalInjectionHandler.drives_autonomy is True


def test_no_goal_intent_while_focused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pin_container_containers_only(monkeypatch)
    pin_session_modes(monkeypatch, tmp_path / "modes", focus_entry(_SESSION))
    with (
        patch.object(GoalInjectionHandler, "matches", return_value=True) as matches,
        patch.object(GoalInjectionHandler, "handle", _signal_writing_handle(tmp_path)),
    ):
        _run(GoalInjectionHandler())
    assert matches.called is False
    assert not (tmp_path / f"{_SESSION}.goal-intent").exists()


def test_without_focus_the_same_chain_writes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control: the gate, not the patching, is what kept the signal away."""
    pin_container_containers_only(monkeypatch)
    pin_session_modes(monkeypatch, tmp_path / "modes")
    with (
        patch.object(GoalInjectionHandler, "matches", return_value=True),
        patch.object(GoalInjectionHandler, "handle", _signal_writing_handle(tmp_path)),
    ):
        _run(GoalInjectionHandler())
    assert (tmp_path / f"{_SESSION}.goal-intent").exists()
