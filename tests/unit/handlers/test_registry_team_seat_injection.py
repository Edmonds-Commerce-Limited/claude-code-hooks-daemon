"""`register_all` injects the `team_seat:` block as `_team_seat` (Plan 00634 Task 2.2).

Selected by declared attribute, like `_scratch`: only a handler that declares
`_team_seat` receives it, and an absent block leaves the declared default.
"""

from __future__ import annotations

import inspect

import pytest

from claude_code_hooks_daemon.config.models import TeamSeatConfig
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.handlers.pre_tool_use.dangerous_permissions import (
    DangerousPermissionsHandler,
)
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

_DECLARED_DEFAULT = TeamSeatConfig()


def _registered(team_seat: TeamSeatConfig | None) -> DangerousPermissionsHandler:
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    registry.register_all(router, config={}, team_seat=team_seat)
    for handler in router.get_chain(EventType.PRE_TOOL_USE).handlers:
        if isinstance(handler, DangerousPermissionsHandler):
            return handler
    raise AssertionError("dangerous_permissions was not registered")


@pytest.fixture
def declares_team_seat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make a real discovered handler declare the attribute, as the guard will."""
    monkeypatch.setattr(DangerousPermissionsHandler, "_team_seat", _DECLARED_DEFAULT, raising=False)


@pytest.mark.usefixtures("declares_team_seat")
def test_the_block_is_injected() -> None:
    team_seat = TeamSeatConfig()
    assert _registered(team_seat)._team_seat is team_seat


@pytest.mark.usefixtures("declares_team_seat")
def test_absent_block_leaves_the_declared_default() -> None:
    assert _registered(None)._team_seat is _DECLARED_DEFAULT


def test_undeclared_handler_receives_nothing() -> None:
    assert not hasattr(_registered(TeamSeatConfig()), "_team_seat")


def test_controller_accepts_and_forwards_team_seat() -> None:
    assert "team_seat" in inspect.signature(DaemonController.initialise).parameters


def test_cli_passes_the_loaded_block() -> None:
    assert "team_seat=config.team_seat" in inspect.getsource(cli)
