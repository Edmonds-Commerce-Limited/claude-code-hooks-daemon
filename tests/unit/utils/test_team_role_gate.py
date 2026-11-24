"""Tests for the per-team role gate (Plan 00631 Phase 3)."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from claude_code_hooks_daemon.utils.team_role_gate import (
    GateVerdict,
    coordinator_advisory_armed,
    duty_gate,
    role_gate,
)
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ProbeReason,
    SeatContext,
    parse_whoami,
)
from tests.support import teamchat as fx

MAIN: dict[str, Any] = {"hook_event_name": "PreToolUse", "session_id": "s1"}
SUBAGENT: dict[str, Any] = {**MAIN, "agent_id": "a1b2c3d4e5f6a7b8c"}

ABSENT = SeatContext.absent(ProbeReason.NO_RUNTIME_SIGNAL)
UNRESOLVED = SeatContext.unresolved(ProbeReason.COMMAND_TIMEOUT)


def test_absent_is_not_applicable() -> None:
    decision = role_gate(MAIN, ABSENT, team="alpha", role="coordinator")
    assert decision.verdict is GateVerdict.NOT_APPLICABLE


def test_coordinator_in_team_applies_on_main_thread() -> None:
    context = parse_whoami(fx.COORDINATOR_ONLY)
    assert role_gate(MAIN, context, team="alpha", role="coordinator").verdict is (
        GateVerdict.APPLIES
    )


def test_subagent_of_coordinator_seat_is_not_coordinator() -> None:
    context = parse_whoami(fx.COORDINATOR_ONLY)
    decision = role_gate(SUBAGENT, context, team="alpha", role="coordinator")
    assert decision.verdict is GateVerdict.NOT_APPLICABLE


# --- include_subagents (Plan 00634 P2): a guard judges a seat's sub-agent as the seat ---


def test_include_subagents_judges_a_coordinator_seats_subagent_as_the_seat() -> None:
    context = parse_whoami(fx.COORDINATOR_ONLY)
    decision = role_gate(
        SUBAGENT, context, team="alpha", role="coordinator", include_subagents=True
    )
    assert decision.verdict is GateVerdict.APPLIES


def test_include_subagents_leaves_a_worker_seats_subagent_not_applicable() -> None:
    context = parse_whoami(fx.WORKER_ONLY)
    decision = role_gate(
        SUBAGENT, context, team="alpha", role="coordinator", include_subagents=True
    )
    assert decision.verdict is GateVerdict.NOT_APPLICABLE


def test_include_subagents_leaves_a_no_team_subagent_not_applicable() -> None:
    decision = role_gate(SUBAGENT, ABSENT, team="alpha", role="coordinator", include_subagents=True)
    assert decision.verdict is GateVerdict.NOT_APPLICABLE


def test_include_subagents_never_arms_a_subagent_on_an_unreadable_role() -> None:
    """Owner ruling (plan 00634): a sub-agent is judged only on a DECLARED role."""
    for context in (UNRESOLVED, parse_whoami(fx.ROLE_NULL)):
        decision = role_gate(
            SUBAGENT, context, team="alpha", role="coordinator", include_subagents=True
        )
        assert decision.verdict is GateVerdict.NOT_APPLICABLE


def test_include_subagents_changes_nothing_on_the_main_thread() -> None:
    for context in (parse_whoami(fx.COORDINATOR_ONLY), parse_whoami(fx.WORKER_ONLY), ABSENT):
        assert role_gate(
            MAIN, context, team="alpha", role="coordinator", include_subagents=True
        ) == role_gate(MAIN, context, team="alpha", role="coordinator")


def test_duty_gate_include_subagents_never_arms_on_an_unreadable_duty() -> None:
    decision = duty_gate(SUBAGENT, UNRESOLVED, duty="host", include_subagents=True)
    assert decision.verdict is GateVerdict.NOT_APPLICABLE


def test_duty_gate_include_subagents_judges_the_seat() -> None:
    context = parse_whoami(fx.HOST_DUTY)
    assert duty_gate(SUBAGENT, context, duty="host", include_subagents=True).verdict is (
        GateVerdict.APPLIES
    )
    assert duty_gate(SUBAGENT, context, duty="host").verdict is GateVerdict.NOT_APPLICABLE


def test_per_team_multi_team() -> None:
    context = parse_whoami(fx.MULTI_TEAM)
    assert role_gate(MAIN, context, team="alpha", role="coordinator").verdict is (
        GateVerdict.APPLIES
    )
    assert role_gate(MAIN, context, team="beta", role="coordinator").verdict is (
        GateVerdict.NOT_APPLICABLE
    )


def test_probe_role_switches_nothing_on() -> None:
    context = parse_whoami(fx.ROLE_PROBE)
    for role in ("coordinator", "worker"):
        assert role_gate(MAIN, context, team="alpha", role=role).verdict is (
            GateVerdict.NOT_APPLICABLE
        )


def test_team_not_held_is_not_applicable() -> None:
    context = parse_whoami(fx.MULTI_TEAM)
    assert role_gate(MAIN, context, team="gamma", role="coordinator").verdict is (
        GateVerdict.NOT_APPLICABLE
    )


@pytest.mark.parametrize(
    "context",
    [UNRESOLVED, parse_whoami(fx.CONFLICTING_ROWS)],
)
def test_unreadable_role_is_role_unknown(context: SeatContext) -> None:
    decision = role_gate(MAIN, context, team="alpha", role="coordinator")
    assert decision.verdict is GateVerdict.ROLE_UNKNOWN


def test_undetermined_team_in_a_team_session_is_role_unknown() -> None:
    context = parse_whoami(fx.COORDINATOR_ONLY)
    assert role_gate(MAIN, context, team="", role="coordinator").verdict is (
        GateVerdict.ROLE_UNKNOWN
    )


@pytest.mark.parametrize("team", ["Alpha", "ALPHA", " alpha "])
def test_team_name_matches_case_insensitively(team: str) -> None:
    """Review F9: a case mismatch must never read as 'no seat here'."""
    context = parse_whoami(fx.COORDINATOR_ONLY)
    assert role_gate(MAIN, context, team=team, role="coordinator").verdict is (GateVerdict.APPLIES)


@pytest.mark.parametrize("team", ["   ", "\t", "\n"])
def test_blank_team_is_role_unknown(team: str) -> None:
    context = parse_whoami(fx.COORDINATOR_ONLY)
    assert role_gate(MAIN, context, team=team, role="coordinator").verdict is (
        GateVerdict.ROLE_UNKNOWN
    )


def test_undetermined_team_without_a_team_is_not_applicable() -> None:
    assert role_gate(MAIN, ABSENT, team="", role="coordinator").verdict is (
        GateVerdict.NOT_APPLICABLE
    )


def test_decision_carries_reason_and_team() -> None:
    decision = role_gate(MAIN, parse_whoami(fx.WORKER_ONLY), team="alpha", role="coordinator")
    assert decision.team == "alpha"
    assert decision.reason


def test_host_as_coordinator_is_role_unknown_not_applies() -> None:
    context = parse_whoami(fx.HOST_AS_COORDINATOR)
    assert role_gate(MAIN, context, team="alpha", role="coordinator").verdict is (
        GateVerdict.ROLE_UNKNOWN
    )


# --- duty gate (acts that name no team) ------------------------------------------


def test_duty_gate_absent_is_not_applicable() -> None:
    assert duty_gate(MAIN, ABSENT, duty="host").verdict is GateVerdict.NOT_APPLICABLE


def test_duty_gate_host_in_any_team_applies() -> None:
    context = parse_whoami(fx.HOST_DUTY)
    assert duty_gate(MAIN, context, duty="host").verdict is GateVerdict.APPLIES
    assert duty_gate(MAIN, context, duty="coordinator").verdict is GateVerdict.NOT_APPLICABLE


def test_duty_gate_subagent_is_not_applicable() -> None:
    context = parse_whoami(fx.HOST_DUTY)
    assert duty_gate(SUBAGENT, context, duty="host").verdict is GateVerdict.NOT_APPLICABLE


@pytest.mark.parametrize("context", [UNRESOLVED, parse_whoami(fx.ROLE_NULL)])
def test_duty_gate_unreadable_duty_is_role_unknown(context: SeatContext) -> None:
    assert duty_gate(MAIN, context, duty="host").verdict is GateVerdict.ROLE_UNKNOWN


def test_duty_gate_unknown_duty_switches_nothing_on() -> None:
    context = parse_whoami(fx.UNKNOWN_DUTY)
    for duty in ("coordinator", "host"):
        assert duty_gate(MAIN, context, duty=duty).verdict is GateVerdict.NOT_APPLICABLE


# --- coordinator advisory arming (Plan 00636 Tasks 2.2 and 2.3) ---------------------


@pytest.mark.parametrize(
    "context",
    [
        parse_whoami(fx.COORDINATOR_ONLY),
        parse_whoami(fx.MULTI_TEAM),
        parse_whoami(fx.ROLE_NULL),
        parse_whoami(fx.HOST_AS_COORDINATOR),
        UNRESOLVED,
    ],
)
def test_coordinator_advisory_arms_a_coordinator_or_an_unreadable_seat(
    context: SeatContext,
) -> None:
    assert coordinator_advisory_armed(MAIN, context) is True


@pytest.mark.parametrize(
    "context",
    [ABSENT, parse_whoami(fx.WORKER_ONLY), parse_whoami(fx.HOST_DUTY), parse_whoami(fx.NO_TEAMS)],
)
def test_coordinator_advisory_leaves_a_worker_or_no_team_untouched(context: SeatContext) -> None:
    assert coordinator_advisory_armed(MAIN, context) is False


def test_coordinator_advisory_never_arms_a_subagent() -> None:
    assert coordinator_advisory_armed(SUBAGENT, parse_whoami(fx.COORDINATOR_ONLY)) is False


def test_gate_can_never_express_an_approval() -> None:
    """Invariant 1: a role only adds conduct; the gate has no allow or approve output."""
    assert {v.value for v in GateVerdict} == {"applies", "role_unknown", "not_applicable"}
    decision = role_gate(MAIN, ABSENT, team="alpha", role="coordinator")
    assert {f.name for f in dataclasses.fields(decision)} == {"verdict", "team", "reason"}
