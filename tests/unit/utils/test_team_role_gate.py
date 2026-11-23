"""Tests for the per-team role gate (Plan 00631 Phase 3)."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from claude_code_hooks_daemon.utils.team_role_gate import GateVerdict, role_gate
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ProbeReason,
    SeatContext,
    parse_whoami,
)
from tests.support import teamchat as fx

MAIN: dict[str, Any] = {"hook_event_name": "PreToolUse", "session_id": "s1"}
SUBAGENT: dict[str, Any] = {**MAIN, "agent_id": "a1b2c3d4e5f6a7b8c"}

ABSENT = SeatContext.absent(ProbeReason.NO_MEMBERSHIP_SIGNAL)
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


def test_per_team_multi_team() -> None:
    context = parse_whoami(fx.MULTI_TEAM)
    assert role_gate(MAIN, context, team="alpha", role="coordinator").verdict is (
        GateVerdict.APPLIES
    )
    assert role_gate(MAIN, context, team="beta", role="coordinator").verdict is (
        GateVerdict.NOT_APPLICABLE
    )


def test_unknown_declared_role_switches_nothing_on() -> None:
    context = parse_whoami(fx.UNKNOWN_ROLE)
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


def test_undetermined_team_without_a_team_is_not_applicable() -> None:
    assert role_gate(MAIN, ABSENT, team="", role="coordinator").verdict is (
        GateVerdict.NOT_APPLICABLE
    )


def test_decision_carries_reason_and_team() -> None:
    decision = role_gate(MAIN, parse_whoami(fx.WORKER_ONLY), team="alpha", role="coordinator")
    assert decision.team == "alpha"
    assert decision.reason


def test_gate_can_never_express_an_approval() -> None:
    """Invariant 1: a role only adds conduct; the gate has no allow or approve output."""
    assert {v.value for v in GateVerdict} == {"applies", "role_unknown", "not_applicable"}
    decision = role_gate(MAIN, ABSENT, team="alpha", role="coordinator")
    assert {f.name for f in dataclasses.fields(decision)} == {"verdict", "team", "reason"}
