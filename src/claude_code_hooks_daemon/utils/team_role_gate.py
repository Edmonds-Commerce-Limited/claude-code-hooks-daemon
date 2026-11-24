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

Main thread only by default: for conduct ADVISORIES a coordinator seat's
sub-agents are not coordinators. A GUARD a sub-agent could otherwise walk
round passes ``include_subagents=True`` (Plan 00634 P2), and a sub-agent is
then judged as its seat on a DECLARED role or duty only. The thread test is
:func:`handler_scope.acts_as_main_thread`, so a synthetic probe event is
treated the same way the scope machinery treats it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from claude_code_hooks_daemon.core.handler_scope import acts_as_main_thread
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ROLE_COORDINATOR,
    RoleKind,
    SeatContext,
    SeatState,
    normalise_name,
)

logger = logging.getLogger(__name__)


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
    hook_input: Mapping[str, Any],
    context: SeatContext,
    *,
    team: str,
    role: str,
    include_subagents: bool = False,
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
        include_subagents: For a GUARD a sub-agent could walk round (Plan
            00634 P2): a sub-agent is judged as its seat, but only on a
            DECLARED role. An unreadable role or team is NOT_APPLICABLE for
            a sub-agent, never ROLE_UNKNOWN, so no team, role or duty is
            assumed off the main thread. Advisories leave it False.
    """
    team = normalise_name(team)
    if context.state is SeatState.ABSENT:
        return RoleGateDecision(GateVerdict.NOT_APPLICABLE, team, "session holds no team seat")
    main_thread = acts_as_main_thread(hook_input)
    if not main_thread and not include_subagents:
        return RoleGateDecision(GateVerdict.NOT_APPLICABLE, team, "sub-agent: roles are per seat")
    unknown = GateVerdict.ROLE_UNKNOWN if main_thread else GateVerdict.NOT_APPLICABLE
    if not team:
        return RoleGateDecision(unknown, team, "the action's team is undetermined")
    answer = context.role_for_team(team)
    if answer.kind is RoleKind.UNKNOWN:
        return RoleGateDecision(unknown, team, "role in this team is unreadable")
    if answer.holds_role(role):
        return RoleGateDecision(GateVerdict.APPLIES, team, f"declared {role} in this team")
    return RoleGateDecision(GateVerdict.NOT_APPLICABLE, team, f"not {role} in this team")


def duty_gate(
    hook_input: Mapping[str, Any],
    context: SeatContext,
    *,
    duty: str,
    include_subagents: bool = False,
) -> RoleGateDecision:
    """Whether ``duty`` in ANY held team applies to this event, for acts that name no team.

    ``APPLIES`` when some held team declares ``duty``; otherwise
    ``ROLE_UNKNOWN`` when the probe gave no answer at all (it might have been
    this one), else ``NOT_APPLICABLE``. An undeclared duty in a resolved seat
    is NOT_APPLICABLE: duty is optional (owner ruling D1). The decision's ``team`` is ``""``.
    ``include_subagents`` is as for :func:`role_gate`: a sub-agent is judged
    on a DECLARED duty only. Never raises.
    """
    if context.state is SeatState.ABSENT:
        return RoleGateDecision(GateVerdict.NOT_APPLICABLE, "", "session holds no team seat")
    main_thread = acts_as_main_thread(hook_input)
    if not main_thread and not include_subagents:
        return RoleGateDecision(GateVerdict.NOT_APPLICABLE, "", "sub-agent: duties are per seat")
    if context.any_duty(duty):
        return RoleGateDecision(GateVerdict.APPLIES, "", f"declared duty {duty} in a held team")
    if main_thread and context.duty_unknown():
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


def probe_coordinator_advisory_armed(
    hook_input: Mapping[str, Any], probe: Callable[[], SeatContext], *, handler: str
) -> bool:
    """:func:`coordinator_advisory_armed`, probing the seat only on the main thread.

    A sub-agent is answered before ``probe`` runs (it is never a coordinator, so
    no ``whoami`` is spent on it). A raising probe counts as armed, logged at
    WARNING naming ``handler``: an advisory only adds text. Never raises.
    """
    if not acts_as_main_thread(hook_input):
        return False
    try:
        return coordinator_advisory_armed(hook_input, probe())
    except Exception as exc:  # the seat probe is a boundary; an advisory only adds text
        log_and_continue(
            logger,
            exc,
            reason=f"{handler} could not read the seat, so it counts as armed: the note only adds advisory text and never blocks",
            level=logging.WARNING,
        )
        return True
