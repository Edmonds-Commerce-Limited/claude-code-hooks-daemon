"""Tests for the coordinator board note (Plan 00636 Task 2.5, s7 and B5).

On SessionStart a coordinator seat is told where peers' state comes from
(`teamchat status`, never teamchat's files) and that a seat it cannot read is
unknown, not down. The handler runs no `teamchat status`, opens no teamchat
file and relays no status text (the only command it runs is the shared
`whoami` seat probe): the `teamchat status` output contract is not
on disk, so nothing is parsed. Advisory only. A declared worker, no team and a
sub-agent are untouched; an unreadable role or probe stays armed.
"""

from __future__ import annotations

import builtins
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from tests.support import teamchat as fx

from claude_code_hooks_daemon.config.models import TeamSeatConfig
from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry
from claude_code_hooks_daemon.handlers.session_start.coordinator_board import (
    CoordinatorBoardHandler,
)
from claude_code_hooks_daemon.utils.teamchat_seat import (
    CommandOutcome,
    CommandStatus,
    ProbeReason,
    RoleKind,
    SeatContext,
    SeatContextResolver,
    SeatState,
    SessionSignals,
    TeamSeat,
    whoami_argv,
)

RUNTIME = "/tmp/teamchat/run-a"
KIT = "/opt/teamchat-kit"


def _seats(role: str | None = "coordinator", duty: str = "coordinator") -> SeatContext:
    kind = RoleKind.DECLARED if role is not None else RoleKind.UNKNOWN
    seat = TeamSeat(team="alpha", role_kind=kind, role=role or "", duty=duty if role else "")
    return SeatContext(SeatState.RESOLVED, ProbeReason.RESOLVED, (seat,))


class _Resolver:
    def __init__(self, context: SeatContext | BaseException) -> None:
        self.context = context
        self.calls = 0

    def resolve(self, signals: SessionSignals) -> SeatContext:
        self.calls += 1
        if isinstance(self.context, BaseException):
            raise self.context
        return self.context


def _handler(context: SeatContext | BaseException | None = None) -> CoordinatorBoardHandler:
    handler = CoordinatorBoardHandler()
    handler._resolver = _Resolver(context if context is not None else _seats())
    return handler


def _input(**extra: Any) -> dict[str, Any]:
    return {"hook_event_name": "SessionStart", "session_id": "s1", "source": "startup", **extra}


def _text(handler: CoordinatorBoardHandler, hook_input: dict[str, Any]) -> str:
    result = handler.handle(hook_input)
    assert result.decision is Decision.ALLOW
    return "\n".join(result.context)


class TestIdentity:
    def test_identity_priority_and_never_terminal(self) -> None:
        handler = CoordinatorBoardHandler()
        assert handler.handler_id == HandlerID.COORDINATOR_BOARD
        assert handler.priority == Priority.COORDINATOR_BOARD
        assert handler.terminal is False
        assert handler.get_default_enabled() is True

    def test_no_resident_guidance_and_an_acceptance_test(self) -> None:
        """The note reaches a coordinator seat each session; CLAUDE.md would reach every project."""
        handler = CoordinatorBoardHandler()
        assert handler.get_claude_md() is None
        assert handler.get_acceptance_tests()

    def test_class_docstring_summary_has_no_rst_double_backticks(self) -> None:
        summary = (CoordinatorBoardHandler.__doc__ or "").strip().splitlines()[0]
        assert "``" not in summary

    def test_matches_every_session_start(self) -> None:
        assert CoordinatorBoardHandler().matches(_input()) is True
        assert CoordinatorBoardHandler().matches(_input(source="compact")) is True


class TestNote:
    def test_coordinator_gets_the_board_note(self) -> None:
        text = _text(_handler(), _input())
        assert "teamchat status" in text
        assert "unknown, not down" in text
        assert "status.json" in text  # names the files it must not read

    def test_note_hedges_where_the_board_lives_and_keeps_unknown_not_down(self) -> None:
        """The note does not assert what teamchat shows: the output contract is not on disk."""
        text = _text(_handler(), _input())
        assert "peers' state, where teamchat shows it, is `teamchat status`" in text
        assert "peers' state, in one view, is `teamchat status`" not in text
        assert "unknown, not down" in text

    def test_note_restarts_and_reassigns_nothing(self) -> None:
        text = _text(_handler(), _input())
        assert "never restarts" in text

    def test_note_carries_no_rule_id_and_no_waiting_wording(self) -> None:
        text = _text(_handler(), _input())
        assert "R-" not in text
        assert "STOPPING BECAUSE" not in text

    def test_coordinator_duty_on_another_role_is_armed(self) -> None:
        assert "teamchat status" in _text(_handler(_seats("probe", "coordinator")), _input())


class TestGate:
    def test_declared_worker_is_untouched(self) -> None:
        assert _text(_handler(_seats("worker", "worker")), _input()) == ""

    def test_no_team_is_untouched(self) -> None:
        absent = SeatContext.absent(ProbeReason.NO_RUNTIME_SIGNAL)
        assert _text(_handler(absent), _input()) == ""

    def test_subagent_is_untouched_and_never_probes(self) -> None:
        handler = _handler()
        assert _text(handler, _input(agent_id="a1b2c3d4e5f6a7b8c")) == ""
        assert isinstance(handler._resolver, _Resolver)
        assert handler._resolver.calls == 0

    def test_unknown_role_stays_armed(self) -> None:
        assert "teamchat status" in _text(_handler(_seats(None)), _input())

    def test_unresolved_probe_stays_armed(self) -> None:
        unresolved = SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
        assert "teamchat status" in _text(_handler(unresolved), _input())

    @pytest.mark.parametrize("exc", [RuntimeError("probe"), RecursionError(), ValueError("x")])
    def test_a_raising_resolver_counts_as_armed_and_never_raises(
        self, exc: BaseException, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            assert "teamchat status" in _text(_handler(exc), _input())

    def test_the_probe_runs_once_per_event(self) -> None:
        handler = _handler()
        _text(handler, _input())
        assert isinstance(handler._resolver, _Resolver)
        assert handler._resolver.calls == 1


class _FakeRunner:
    """Answers the whoami probe with a fixed outcome and records each argv."""

    def __init__(self, outcome: CommandOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self, args: Sequence[str], env_overlay: Mapping[str, str], timeout: float
    ) -> CommandOutcome:
        self.calls.append(tuple(args))
        return self.outcome


def _registered() -> CoordinatorBoardHandler:
    """The handler as the daemon builds it: discovered and registered with a team_seat block."""
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    team_seat = TeamSeatConfig()
    registry.register_all(router, config={}, team_seat=team_seat)
    for handler in router.get_chain(EventType.SESSION_START).handlers:
        if isinstance(handler, CoordinatorBoardHandler):
            assert handler._team_seat is team_seat
            return handler
    raise AssertionError("coordinator_board was not registered on SessionStart")


def _stamped(**extra: Any) -> dict[str, Any]:
    """A SessionStart payload carrying the seat signals the server stamps on every event."""
    return _input(
        **{HookInputField.TEAMCHAT_RUNTIME: RUNTIME, HookInputField.TEAMCHAT_KIT: KIT}, **extra
    )


def _with_runner(handler: CoordinatorBoardHandler, runner: _FakeRunner) -> CoordinatorBoardHandler:
    assert handler._team_seat is not None
    handler._resolver = SeatContextResolver.from_config(handler._team_seat, runner=runner)
    return handler


def _record_opens(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    opened: list[str] = []
    real_open = builtins.open

    def spy(file: Any, *args: Any, **kwargs: Any) -> Any:
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    return opened


class TestRealDispatch:
    """Registered handler, real resolver and whoami parser; only the subprocess is faked."""

    def test_a_coordinator_seat_gets_the_note(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runner = _FakeRunner(CommandOutcome(CommandStatus.OK, fx.COORDINATOR_ONLY, 0))
        handler = _with_runner(_registered(), runner)
        opened = _record_opens(monkeypatch)
        assert "teamchat status" in _text(handler, _stamped())
        # Only `whoami` runs (never `status`), and nothing is opened: no file at all,
        # so nothing under the seat store, state root or run directory (invariant 5).
        assert runner.calls == [whoami_argv(KIT)]
        assert opened == []

    def test_a_worker_seat_gets_nothing(self) -> None:
        runner = _FakeRunner(CommandOutcome(CommandStatus.OK, fx.WORKER_ONLY, 0))
        assert _text(_with_runner(_registered(), runner), _stamped()) == ""

    def test_whoami_exit_69_is_no_team_and_silent(self) -> None:
        runner = _FakeRunner(CommandOutcome(CommandStatus.EXITED, "", fx.EXIT_NO_SESSION))
        assert _text(_with_runner(_registered(), runner), _stamped()) == ""

    def test_no_seat_signals_is_silent_and_runs_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = _FakeRunner(CommandOutcome(CommandStatus.OK, fx.COORDINATOR_ONLY, 0))
        handler = _with_runner(_registered(), runner)
        opened = _record_opens(monkeypatch)
        assert _text(handler, _input()) == ""
        assert runner.calls == []
        assert opened == []

    def test_a_subagent_never_probes(self) -> None:
        runner = _FakeRunner(CommandOutcome(CommandStatus.OK, fx.COORDINATOR_ONLY, 0))
        handler = _with_runner(_registered(), runner)
        assert _text(handler, _stamped(agent_id="a1b2c3d4e5f6a7b8c")) == ""
        assert runner.calls == []
