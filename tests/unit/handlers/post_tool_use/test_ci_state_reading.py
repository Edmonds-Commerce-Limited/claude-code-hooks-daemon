"""Tests for the ci-state reading handler (Plan 00636 Task 2.3, s5).

After a ``gh run list`` / ``gh run view --json`` / ``gh pr checks`` on a
coordinator seat, the handler reads the output already printed and tells a
GitHub run that is QUEUED from one that is STUCK, with the rule never to assert
another seat's code without asking it. Advisory only: it never denies and runs
no command of its own. A declared worker, no team and a sub-agent are untouched.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.ci_state_reading import (
    DEFAULT_STUCK_AFTER_MINUTES,
    CiStateReadingHandler,
)
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ProbeReason,
    RoleKind,
    SeatContext,
    SeatState,
    SessionSignals,
    TeamSeat,
)

NOW = datetime(2026, 11, 24, 6, 0, 0, tzinfo=UTC)
COMMAND = "gh run list --limit 5"


def _row(status: str, created: str) -> str:
    return "\t".join(
        [status, "", "Merge pull request #237", "QA", "main", "push", "45334494394", "1s", created]
    )


QUEUED_RECENT = _row("queued", "2026-11-24T05:56:00Z")
QUEUED_OLD = _row("queued", "2026-11-24T05:00:00Z")


def _seats(role: str | None = "coordinator") -> SeatContext:
    kind = RoleKind.DECLARED if role is not None else RoleKind.UNKNOWN
    seat = TeamSeat(team="alpha", role_kind=kind, role=role or "", duty="lead" if role else "")
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
    context: SeatContext | Exception | None = None, stuck_after: object = 30
) -> CiStateReadingHandler:
    handler = CiStateReadingHandler()
    handler._stuck_after_minutes = stuck_after
    handler._resolver = _Resolver(context if context is not None else _seats())
    handler._clock = lambda: NOW
    return handler


def _input(command: str = COMMAND, stdout: str = QUEUED_RECENT, **extra: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": stdout, "stderr": "", "interrupted": False},
        **extra,
    }


def _text(handler: CiStateReadingHandler, hook_input: dict[str, Any]) -> str:
    result = handler.handle(hook_input)
    assert result.decision is Decision.ALLOW
    return "\n".join(result.context)


class TestIdentity:
    def test_identity_priority_and_never_terminal(self) -> None:
        handler = CiStateReadingHandler()
        assert handler.handler_id == HandlerID.CI_STATE_READING
        assert handler.priority == Priority.CI_STATE_READING
        assert handler.terminal is False
        assert handler.get_default_enabled() is True

    def test_has_resident_guidance_and_an_acceptance_test(self) -> None:
        handler = CiStateReadingHandler()
        guidance = handler.get_claude_md() or ""
        assert "without asking that seat" in guidance
        assert handler.get_acceptance_tests()


class TestMatches:
    def test_a_gh_ci_command_matches(self) -> None:
        assert CiStateReadingHandler().matches(_input()) is True

    @pytest.mark.parametrize(
        "command", ['echo "gh run list"', "gh run view 1", "git status", "gh pr view 1 --comments"]
    )
    def test_other_commands_do_not_match(self, command: str) -> None:
        assert CiStateReadingHandler().matches(_input(command=command)) is False

    def test_another_tool_does_not_match(self) -> None:
        assert CiStateReadingHandler().matches({**_input(), "tool_name": "Read"}) is False


class TestGate:
    def test_coordinator_gets_the_queued_reading(self) -> None:
        text = _text(_handler(), _input())
        assert "QUEUED" in text
        assert "not stuck" in text

    def test_coordinator_gets_the_stuck_reading(self) -> None:
        assert "STUCK" in _text(_handler(), _input(stdout=QUEUED_OLD))

    def test_declared_worker_is_untouched(self) -> None:
        assert _text(_handler(_seats("worker")), _input()) == ""

    def test_no_team_is_untouched(self) -> None:
        absent = SeatContext.absent(ProbeReason.NO_RUNTIME_SIGNAL)
        assert _text(_handler(absent), _input(stdout=QUEUED_OLD)) == ""

    def test_subagent_is_untouched(self) -> None:
        assert _text(_handler(), _input(agent_id="a1b2c3d4e5f6a7b8c")) == ""

    def test_unknown_role_stays_armed(self) -> None:
        assert "QUEUED" in _text(_handler(_seats(None)), _input())

    def test_unresolved_probe_stays_armed(self) -> None:
        unresolved = SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
        assert "QUEUED" in _text(_handler(unresolved), _input())

    def test_a_raising_resolver_counts_as_armed(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            assert "QUEUED" in _text(_handler(RuntimeError("probe")), _input())

    def test_nothing_to_say_never_probes(self) -> None:
        handler = _handler()
        assert _text(handler, _input(stdout=_row("completed", "2026-11-24T05:00:00Z"))) == ""
        assert isinstance(handler._resolver, _Resolver)
        assert handler._resolver.calls == 0


class TestReadings:
    def test_unreadable_time_is_unknown(self) -> None:
        text = _text(_handler(), _input(stdout=_row("queued", "soon")))
        assert "UNKNOWN" in text
        assert "STUCK" not in text

    def test_reshaped_output_is_unknown(self) -> None:
        text = _text(_handler(), _input(command="gh run list --jq '.[].status'", stdout="queued\n"))
        assert "UNKNOWN" in text

    def test_pr_checks_pending_is_unsplit(self) -> None:
        stdout = "\t".join(["tests", "pending", "0", "u", ""])
        text = _text(_handler(), _input(command="gh pr checks 1", stdout=stdout))
        assert "PENDING" in text

    def test_a_missing_tool_response_says_nothing(self) -> None:
        hook_input = _input()
        del hook_input["tool_response"]
        assert _text(_handler(), hook_input) == ""

    def test_the_threshold_option_is_honoured(self) -> None:
        assert "STUCK" in _text(_handler(stuck_after=2), _input())

    @pytest.mark.parametrize("bad", [0, -5, 100000, "30", True, None, 2.5])
    def test_an_invalid_threshold_falls_back_to_the_default(
        self, bad: object, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            text = _text(_handler(stuck_after=bad), _input())
        assert f"{DEFAULT_STUCK_AFTER_MINUTES} min" in text
        assert "stuck_after_minutes" in caplog.text
