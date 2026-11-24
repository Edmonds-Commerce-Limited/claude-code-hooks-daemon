"""Per-team role gate and any-team duty gate for handlers (Plan 00631 Phase 3).

Acts that NAME a team use :func:`role_gate`; acts that concern no team use
:func:`duty_gate` (``any_duty``). Both return the same three verdicts.

A handler that adds role-specific conduct asks one question: does role R, in
the team T this action concerns, apply on this thread? The answer is one of
three verdicts:

- ``APPLIES``: main thread, and teamchat declares role R for this session in T.
- ``ROLE_UNKNOWN``: the session is in a team but R cannot be read for T (the
  probe is degraded, rows conflict, or the action's team could not be
  determined). The caller's guards stay armed: an unreadable state must never
  silently disarm a seat. What "armed" means is each guard's decision.
- ``NOT_APPLICABLE``: no team, a sub-agent, a team this session holds no seat
  in, or a different role (including any role this daemon has no behaviour
  for). No behaviour change.

A role only ever ADDS conduct. The gate has no allow, approve or bypass
verdict, so no handler can use a detected role to relax an existing guard.

Main thread only: a coordinator seat's sub-agents are not coordinators. The
thread test is :func:`handler_scope.acts_as_main_thread`, so a synthetic probe
event is treated the same way the scope machinery treats it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from claude_code_hooks_daemon.core.handler_scope import acts_as_main_thread
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ROLE_COORDINATOR,
    RoleKind,
    SeatContext,
    SeatState,
    normalise_name,
)


class GateVerdict(StrEnum):
    APPLIES = "applies"
    ROLE_UNKNOWN = "role_unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class RoleGateDecision:
    verdict: GateVerdict
    team: str
    reason: str


def role_gate(
    hook_input: Mapping[str, Any], context: SeatContext, *, team: str, role: str
) -> RoleGateDecision:
    """Whether ``role`` in ``team`` applies to this event. Never raises.

    Args:
        hook_input: The event payload (for the main-thread test).
        context: The session's resolved seat context.
        team: The team the ACTION concerns; ``""`` when it cannot be determined.
            Matched in :func:`normalise_name` form (stripped, case folded), so
            ``Alpha`` finds teamchat's ``alpha``. A name that does not
            normalise (blank, odd characters) is undetermined: ROLE_UNKNOWN.
        role: The role whose conduct the caller would add.
    """
    team = normalise_name(team)
    if context.state is SeatState.ABSENT:
        return RoleGateDecision(GateVerdict.NOT_APPLICABLE, team, "session holds no team seat")
    if not acts_as_main_thread(hook_input):
        return RoleGateDecision(GateVerdict.NOT_APPLICABLE, team, "sub-agent: roles are per seat")
    if not team:
        return RoleGateDecision(GateVerdict.ROLE_UNKNOWN, team, "the action's team is undetermined")
    answer = context.role_for_team(team)
    if answer.kind is RoleKind.UNKNOWN:
        return RoleGateDecision(GateVerdict.ROLE_UNKNOWN, team, "role in this team is unreadable")
    if answer.holds_role(role):
        return RoleGateDecision(GateVerdict.APPLIES, team, f"declared {role} in this team")
    return RoleGateDecision(GateVerdict.NOT_APPLICABLE, team, f"not {role} in this team")


def duty_gate(
    hook_input: Mapping[str, Any], context: SeatContext, *, duty: str
) -> RoleGateDecision:
    """Whether ``duty`` in ANY held team applies to this event, for acts that name no team.

    ``APPLIES`` when some held team declares ``duty``; otherwise
    ``ROLE_UNKNOWN`` when some duty could not be read (it might have been
    this one), else ``NOT_APPLICABLE``. The decision's ``team`` is ``""``.
    Never raises.
    """
    if context.state is SeatState.ABSENT:
        return RoleGateDecision(GateVerdict.NOT_APPLICABLE, "", "session holds no team seat")
    if not acts_as_main_thread(hook_input):
        return RoleGateDecision(GateVerdict.NOT_APPLICABLE, "", "sub-agent: duties are per seat")
    if context.any_duty(duty):
        return RoleGateDecision(GateVerdict.APPLIES, "", f"declared duty {duty} in a held team")
    if context.duty_unknown():
        return RoleGateDecision(GateVerdict.ROLE_UNKNOWN, "", "a held team's duty is unreadable")
    return RoleGateDecision(GateVerdict.NOT_APPLICABLE, "", f"no held team has duty {duty}")


_ADVISORY_ARMED: tuple[GateVerdict, ...] = (GateVerdict.APPLIES, GateVerdict.ROLE_UNKNOWN)


def coordinator_advisory_armed(hook_input: Mapping[str, Any], context: SeatContext) -> bool:
    """Whether a coordinator ADVISORY speaks on this event (Plan 00636 Tasks 2.2, 2.3).

    Armed: a declared coordinator in any held team, a coordinator duty, an
    unreadable role, or a probe that resolved nothing (as
    ``owner_wait_stop_guard`` arms; an advisory only adds text, so an
    unreadable state keeps it on). Untouched: a declared other role, no team
    and a sub-agent. Never raises.
    """
    if context.state is SeatState.UNRESOLVED:
        gate = role_gate(hook_input, context, team="", role=ROLE_COORDINATOR)
        return gate.verdict in _ADVISORY_ARMED
    for team in context.teams_held():
        if role_gate(hook_input, context, team=team, role=ROLE_COORDINATOR).verdict in (
            _ADVISORY_ARMED
        ):
            return True
    return duty_gate(hook_input, context, duty=ROLE_COORDINATOR).verdict is GateVerdict.APPLIES
