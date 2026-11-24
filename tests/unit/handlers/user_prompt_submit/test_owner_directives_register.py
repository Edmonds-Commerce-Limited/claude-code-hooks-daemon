"""Tests for the owner directives register handler (Plan 00636 Task 2.2, s3).

A directive the owner gave once is recorded once in config and replayed to a
coordinator seat, so the seat checks the register instead of asking again.
Advisory only: it never denies, so no refuse/continue loop can form.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.user_prompt_submit.owner_directives_register import (
    OwnerDirectivesRegisterHandler,
)
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ProbeReason,
    RoleKind,
    SeatContext,
    SeatState,
    SessionSignals,
    TeamSeat,
)

DIRECTIVES = [{"id": "no-squash", "text": "Never squash-merge; use a merge commit."}]
PROMPT = "please carry on with the next branch"


def _seats(role: str | None = "coordinator", duty: str = "lead") -> SeatContext:
    kind = RoleKind.DECLARED if role is not None else RoleKind.UNKNOWN
    seat = TeamSeat(team="alpha", role_kind=kind, role=role or "", duty=duty if role else "")
    return SeatContext(SeatState.RESOLVED, ProbeReason.RESOLVED, (seat,))


class _Resolver:
    def __init__(self, context: SeatContext | Exception) -> None:
        self.context = context
        self.calls = 0

    def resolve(self, signals: SessionSignals) -> SeatContext:
        self.calls += 1
        if isinstance(self.context, Exception):
            raise self.context
        return self.context


def _handler(
    context: SeatContext | Exception | None = None,
    directives: object = DIRECTIVES,
    interval: object = 3,
) -> OwnerDirectivesRegisterHandler:
    handler = OwnerDirectivesRegisterHandler()
    handler._directives = directives
    handler._prompt_interval = interval
    handler._resolver = _Resolver(context if context is not None else _seats())
    return handler


def _input(prompt: str = PROMPT, session: str = "s1", **extra: Any) -> dict[str, Any]:
    return {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "session_id": session, **extra}


class TestIdentity:
    def test_identity_priority_and_never_terminal(self) -> None:
        handler = OwnerDirectivesRegisterHandler()
        assert handler.handler_id == HandlerID.OWNER_DIRECTIVES_REGISTER
        assert handler.priority == Priority.OWNER_DIRECTIVES_REGISTER
        assert handler.terminal is False

    def test_enabled_by_default_and_silent_with_an_empty_register(self) -> None:
        handler = OwnerDirectivesRegisterHandler()
        assert handler.get_default_enabled() is True
        result = handler.handle(_input())
        assert result.decision is Decision.ALLOW
        assert result.context == []


class TestGate:
    def test_declared_coordinator_gets_the_register(self) -> None:
        result = _handler().handle(_input())
        assert result.decision is Decision.ALLOW
        assert "\n".join(result.context).count("[no-squash]") == 1

    def test_a_directive_recorded_twice_is_replayed_once(self) -> None:
        twice = [
            *DIRECTIVES,
            {"id": "other-id", "text": "never  squash-merge; use a MERGE commit."},
        ]
        text = "\n".join(_handler(directives=twice).handle(_input()).context)
        assert text.lower().count("squash-merge") == 1

    def test_declared_worker_is_untouched(self) -> None:
        assert _handler(_seats("worker")).handle(_input()).context == []

    def test_no_team_is_untouched(self) -> None:
        absent = SeatContext.absent(ProbeReason.NO_RUNTIME_SIGNAL)
        assert _handler(absent).handle(_input()).context == []

    def test_unknown_role_stays_armed_like_the_owner_wait_guard(self) -> None:
        assert _handler(_seats(None)).handle(_input()).context != []

    def test_unresolved_probe_stays_armed(self) -> None:
        unresolved = SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
        assert _handler(unresolved).handle(_input()).context != []

    def test_a_coordinator_duty_arms_a_seat_of_another_role(self) -> None:
        assert _handler(_seats("worker", duty="coordinator")).handle(_input()).context != []

    def test_sub_agent_is_untouched(self) -> None:
        assert _handler().handle(_input(agent_id="sub-1")).context == []

    def test_a_raising_resolver_is_logged_and_the_seat_counts_as_armed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = _handler(RuntimeError("boom")).handle(_input())
        assert result.decision is Decision.ALLOW
        assert result.context != []
        assert "owner_directives_register" in caplog.text

    def test_empty_register_never_probes_the_seat(self) -> None:
        handler = OwnerDirectivesRegisterHandler()
        resolver = _Resolver(_seats())
        handler._resolver = resolver
        handler.handle(_input())
        assert resolver.calls == 0


class TestCadence:
    def test_first_prompt_delivers_then_silent_until_the_interval(self) -> None:
        handler = _handler(interval=3)
        assert handler.handle(_input()).context != []
        assert handler.handle(_input()).context == []
        assert handler.handle(_input()).context == []
        assert handler.handle(_input()).context != []

    def test_automated_turns_neither_count_nor_deliver(self) -> None:
        handler = _handler(interval=2)
        handler.handle(_input())
        tick = _input("**FAILSAFE RECOVERY CHECK (automated hourly safety net ...)**")
        for _ in range(5):
            assert handler.handle(tick).context == []
        assert handler.handle(_input()).context == []
        assert handler.handle(_input()).context != []

    def test_tracked_per_session(self) -> None:
        handler = _handler()
        assert handler.handle(_input(session="a")).context != []
        assert handler.handle(_input(session="b")).context != []

    def test_a_worker_prompt_does_not_consume_the_first_delivery(self) -> None:
        handler = _handler(_seats("worker"))
        handler.handle(_input())
        handler._resolver = _Resolver(_seats())
        assert handler.handle(_input()).context != []

    @pytest.mark.parametrize("interval", [0, -1, True, "5", 1.5, 10_001, None])
    def test_invalid_interval_falls_back_to_the_default_with_a_warning(
        self, interval: object, caplog: pytest.LogCaptureFixture
    ) -> None:
        handler = _handler(interval=interval)
        with caplog.at_level(logging.WARNING):
            assert handler.handle(_input()).context != []
        assert "prompt_interval" in caplog.text


class TestBadOptions:
    def test_non_list_register_is_reported_and_silent(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = _handler(directives="no-squash").handle(_input())
        assert result.context == []
        assert "not a list" in caplog.text

    def test_a_bad_entry_does_not_silence_the_good_ones(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = _handler(directives=["junk", *DIRECTIVES]).handle(_input())
        assert "[no-squash]" in "\n".join(result.context)
        assert "not a mapping" in caplog.text

    def test_matches_only_a_string_prompt(self) -> None:
        assert OwnerDirectivesRegisterHandler().matches({"prompt": 3}) is False
        assert OwnerDirectivesRegisterHandler().matches(_input()) is True


class TestNeverDenies:
    def test_the_replayed_text_is_not_a_countermand(self) -> None:
        text = "\n".join(_handler().handle(_input()).context).lower()
        for word in ("ignore", "override", "disregard"):
            assert word not in text


class TestDefaultSeams:
    def test_the_default_resolver_answers_absent_without_team_signals(self) -> None:
        handler = OwnerDirectivesRegisterHandler()
        handler._directives = DIRECTIVES
        assert handler.handle(_input()).context == []

    def test_guidance_and_acceptance_tests(self) -> None:
        handler = OwnerDirectivesRegisterHandler()
        assert handler.get_claude_md() is None
        tests = handler.get_acceptance_tests()
        assert len(tests) == 1
        assert tests[0].expected_message_patterns == []
