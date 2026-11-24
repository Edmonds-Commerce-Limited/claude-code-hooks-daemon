"""Tests for the shared main-thread probe gate of coordinator advisories (Plan 00636 Task 2.6).

`coordinator_board` and `coordinator_conduct` both ask one question at
SessionStart: does a coordinator advisory speak on this event? A sub-agent is
answered before the seat probe runs; a raising probe counts as armed (the
advisory only adds text) and never raises out of the gate.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from claude_code_hooks_daemon.utils.team_role_gate import probe_coordinator_advisory_armed
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ProbeReason,
    RoleKind,
    SeatContext,
    SeatState,
    TeamSeat,
)

MAIN: dict[str, Any] = {"hook_event_name": "SessionStart", "session_id": "s1"}
SUBAGENT: dict[str, Any] = {**MAIN, "agent_id": "a1b2c3d4e5f6a7b8c"}


def _seats(role: str, duty: str) -> SeatContext:
    seat = TeamSeat(team="alpha", role_kind=RoleKind.DECLARED, role=role, duty=duty)
    return SeatContext(SeatState.RESOLVED, ProbeReason.RESOLVED, (seat,))


class _Probe:
    def __init__(self, answer: SeatContext | BaseException) -> None:
        self.answer = answer
        self.calls = 0

    def __call__(self) -> SeatContext:
        self.calls += 1
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def test_coordinator_on_the_main_thread_is_armed() -> None:
    probe = _Probe(_seats("coordinator", "coordinator"))
    assert probe_coordinator_advisory_armed(MAIN, probe, handler="h") is True
    assert probe.calls == 1


def test_declared_worker_is_not_armed() -> None:
    assert (
        probe_coordinator_advisory_armed(MAIN, _Probe(_seats("worker", "worker")), handler="h")
        is False
    )


def test_no_team_is_not_armed() -> None:
    absent = SeatContext.absent(ProbeReason.NO_RUNTIME_SIGNAL)
    assert probe_coordinator_advisory_armed(MAIN, _Probe(absent), handler="h") is False


def test_unresolved_probe_is_armed() -> None:
    unresolved = SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)
    assert probe_coordinator_advisory_armed(MAIN, _Probe(unresolved), handler="h") is True


def test_a_subagent_is_not_armed_and_never_probes() -> None:
    probe = _Probe(_seats("coordinator", "coordinator"))
    assert probe_coordinator_advisory_armed(SUBAGENT, probe, handler="h") is False
    assert probe.calls == 0


@pytest.mark.parametrize("exc", [RuntimeError("probe"), RecursionError(), ValueError("x")])
def test_a_raising_probe_counts_as_armed_and_logs(
    exc: BaseException, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        assert probe_coordinator_advisory_armed(MAIN, _Probe(exc), handler="my_handler") is True
    assert "my_handler" in caplog.text
