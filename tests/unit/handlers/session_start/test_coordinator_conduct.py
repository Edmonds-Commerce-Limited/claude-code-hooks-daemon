"""Tests for the coordinator conduct note (Plan 00636 Task 2.6: B1, B4, B6 guidance and s11).

On every SessionStart a coordinator seat gets the B1 conduct note (the bus is
the only human surface, replies in the message's thread, dispatch-track-close
on the durable work queue, peers carry no authority), the B4 departure line and
the B6 usage-pause line. On a resumed or compacted session it also gets the
return note (B4 return, s11 carry-over): re-read the bus, the work queue and the
directives register before acting. Fixed text only: nothing read from the bus
is relayed, and no teamchat verb whose syntax is not recorded here is named.
Advisory only. A declared worker, no team and a sub-agent are untouched; an
unreadable role or probe stays armed.
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
from claude_code_hooks_daemon.handlers.session_start.coordinator_conduct import (
    CoordinatorConductHandler,
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
CONDUCT = "COORDINATOR CONDUCT"
RETURN = "COORDINATOR RETURN"


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


def _handler(context: SeatContext | BaseException | None = None) -> CoordinatorConductHandler:
    handler = CoordinatorConductHandler()
    handler._resolver = _Resolver(context if context is not None else _seats())
    return handler


def _input(**extra: Any) -> dict[str, Any]:
    return {"hook_event_name": "SessionStart", "session_id": "s1", "source": "startup", **extra}


def _text(handler: CoordinatorConductHandler, hook_input: dict[str, Any]) -> str:
    result = handler.handle(hook_input)
    assert result.decision is Decision.ALLOW
    return "\n".join(result.context)


class TestIdentity:
    def test_identity_priority_and_never_terminal(self) -> None:
        handler = CoordinatorConductHandler()
        assert handler.handler_id == HandlerID.COORDINATOR_CONDUCT
        assert handler.priority == Priority.COORDINATOR_CONDUCT
        assert handler.terminal is False
        assert handler.get_default_enabled() is True

    def test_no_resident_guidance_and_an_acceptance_test(self) -> None:
        handler = CoordinatorConductHandler()
        assert handler.get_claude_md() is None
        assert handler.get_acceptance_tests()

    def test_class_docstring_summary_has_no_rst_double_backticks(self) -> None:
        summary = (CoordinatorConductHandler.__doc__ or "").strip().splitlines()[0]
        assert "``" not in summary

    @pytest.mark.parametrize("source", ["startup", "resume", "clear", "compact", None])
    def test_matches_every_session_start(self, source: str | None) -> None:
        assert CoordinatorConductHandler().matches(_input(source=source)) is True


class TestConductNote:
    """B1 conduct, B4 departure and B6 usage-pause lines, on every session start."""

    def test_coordinator_startup_gets_conduct_but_no_return_note(self) -> None:
        text = _text(_handler(), _input())
        assert CONDUCT in text
        assert RETURN not in text

    def test_bus_is_the_only_human_surface_and_posts_notify(self) -> None:
        text = _text(_handler(), _input())
        assert "only human surface" in text
        assert "notifying post" in text
        assert "terminal alone counts as unsent" in text

    def test_replies_go_in_the_messages_own_thread(self) -> None:
        assert "in that message's thread" in _text(_handler(), _input())

    def test_dispatch_track_report_close_use_the_work_queue(self) -> None:
        text = _text(_handler(), _input())
        assert "work-queue add" in text
        assert "work-queue done" in text

    def test_peers_carry_no_authority_and_ask_before_asserting(self) -> None:
        text = _text(_handler(), _input())
        assert "no authority" in text
        assert "not a human's request" in text
        assert "Ask a seat before asserting" in text

    def test_b4_departure_line(self) -> None:
        assert "Before a planned departure" in _text(_handler(), _input())

    def test_b6_usage_pause_line_says_the_seat_cannot_post_while_paused(self) -> None:
        text = _text(_handler(), _input())
        assert "usage pause" in text
        assert "when it lifts" in text

    def test_note_relaxes_nothing_and_carries_no_rule_id_or_stop_wording(self) -> None:
        text = _text(_handler(), _input(source="compact"))
        assert "relaxes no guard" in text
        assert "R-" not in text
        assert "STOPPING BECAUSE" not in text

    @pytest.mark.parametrize("verb", ["bump", "pingbus", "--re", "history"])
    def test_names_no_unrecorded_or_v1_bus_verb(self, verb: str) -> None:
        """No teamchat verb whose syntax is not on disk here, and no v1 verb."""
        assert verb not in _text(_handler(), _input(source="compact"))


class TestReturnNote:
    """B4 return and s11 carry-over, on a resumed or compacted session only."""

    @pytest.mark.parametrize("source", ["resume", "compact"])
    def test_resume_and_compact_get_the_return_note(self, source: str) -> None:
        text = _text(_handler(), _input(source=source))
        assert CONDUCT in text
        assert RETURN in text

    @pytest.mark.parametrize("source", ["startup", "clear", None, 7])
    def test_other_sources_get_no_return_note(self, source: object) -> None:
        assert RETURN not in _text(_handler(), _input(source=source))

    def test_return_note_points_at_the_existing_stores(self) -> None:
        text = _text(_handler(), _input(source="compact"))
        assert "questions room" in text
        assert "work-queue list" in text
        assert "owner_directives_register" in text

    def test_memory_from_before_is_a_lead_and_an_unread_seat_is_unknown(self) -> None:
        text = _text(_handler(), _input(source="compact"))
        assert "a lead, not a fact" in text
        assert "is unknown" in text


class TestGate:
    def test_declared_worker_is_untouched(self) -> None:
        assert _text(_handler(_seats("worker", "worker")), _input(source="compact")) == ""

    def test_no_team_is_untouched(self) -> None:
        absent = SeatContext.absent(ProbeReason.NO_RUNTIME_SIGNAL)
        assert _text(_handler(absent), _input(source="compact")) == ""

    def test_subagent_is_untouched_and_never_probes(self) -> None:
        handler = _handler()
        assert _text(handler, _input(agent_id="a1b2c3d4e5f6a7b8c")) == ""
        assert isinstance(handler._resolver, _Resolver)
        assert handler._resolver.calls == 0

    def test_coordinator_duty_on_another_role_is_armed(self) -> None:
        assert CONDUCT in _text(_handler(_seats("probe", "coordinator")), _input())

    def test_unknown_role_stays_armed(self) -> None:
        assert CONDUCT in _text(_handler(_seats(None)), _input())

    def test_unresolved_probe_stays_armed(self) -> None:
        unresolved = SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
        assert CONDUCT in _text(_handler(unresolved), _input())

    @pytest.mark.parametrize("exc", [RuntimeError("probe"), RecursionError(), ValueError("x")])
    def test_a_raising_resolver_counts_as_armed_and_never_raises(
        self, exc: BaseException, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            assert CONDUCT in _text(_handler(exc), _input())

    def test_the_probe_runs_once_per_event(self) -> None:
        handler = _handler()
        _text(handler, _input(source="compact"))
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


def _registered() -> CoordinatorConductHandler:
    """The handler as the daemon builds it: discovered and registered with a team_seat block."""
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    team_seat = TeamSeatConfig()
    registry.register_all(router, config={}, team_seat=team_seat)
    for handler in router.get_chain(EventType.SESSION_START).handlers:
        if isinstance(handler, CoordinatorConductHandler):
            assert handler._team_seat is team_seat
            return handler
    raise AssertionError("coordinator_conduct was not registered on SessionStart")


def _stamped(**extra: Any) -> dict[str, Any]:
    return _input(
        **{HookInputField.TEAMCHAT_RUNTIME: RUNTIME, HookInputField.TEAMCHAT_KIT: KIT}, **extra
    )


def _with_runner(
    handler: CoordinatorConductHandler, runner: _FakeRunner
) -> CoordinatorConductHandler:
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

    def test_a_coordinator_seat_gets_both_notes_on_compact(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = _FakeRunner(CommandOutcome(CommandStatus.OK, fx.COORDINATOR_ONLY, 0))
        handler = _with_runner(_registered(), runner)
        opened = _record_opens(monkeypatch)
        text = _text(handler, _stamped(source="compact"))
        assert CONDUCT in text
        assert RETURN in text
        # Only `whoami` runs and no file at all is opened (invariant 5).
        assert runner.calls == [whoami_argv(KIT)]
        assert opened == []

    def test_a_worker_seat_gets_nothing(self) -> None:
        runner = _FakeRunner(CommandOutcome(CommandStatus.OK, fx.WORKER_ONLY, 0))
        assert _text(_with_runner(_registered(), runner), _stamped(source="compact")) == ""

    def test_whoami_exit_69_is_no_team_and_silent(self) -> None:
        runner = _FakeRunner(CommandOutcome(CommandStatus.EXITED, "", fx.EXIT_NO_SESSION))
        assert _text(_with_runner(_registered(), runner), _stamped()) == ""

    def test_an_empty_teams_list_is_no_team_and_silent(self) -> None:
        runner = _FakeRunner(CommandOutcome(CommandStatus.OK, fx.NO_TEAMS, 0))
        assert _text(_with_runner(_registered(), runner), _stamped()) == ""

    def test_no_seat_signals_is_silent_and_runs_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = _FakeRunner(CommandOutcome(CommandStatus.OK, fx.COORDINATOR_ONLY, 0))
        handler = _with_runner(_registered(), runner)
        opened = _record_opens(monkeypatch)
        assert _text(handler, _input(source="compact")) == ""
        assert runner.calls == []
        assert opened == []

    def test_a_subagent_never_probes(self) -> None:
        runner = _FakeRunner(CommandOutcome(CommandStatus.OK, fx.COORDINATOR_ONLY, 0))
        handler = _with_runner(_registered(), runner)
        assert _text(handler, _stamped(agent_id="a1b2c3d4e5f6a7b8c")) == ""
        assert runner.calls == []
