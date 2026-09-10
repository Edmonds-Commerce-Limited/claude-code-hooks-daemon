"""Check ``header-body-coherence`` (Stage 1 + 3, block; sins A3, A1).

A plan whose header claims ``Not Started`` or ``In Progress`` but whose body
already claims completion (every checkbox ticked, or a prose "all done"
marker) is lying to the reader: the header is the source of truth tooling
reads, and it must not contradict the body it summarises. Registered at EDIT
*and* SWEEP (Plan 00230) — a plan that drifted into this state is precisely
the "finished work still marked In Progress" rot the sweep exists to surface.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    DocumentRuleChecks,
    DocumentTarget,
    document_rule_checks,
    level_for_plan,
)
from claude_code_hooks_daemon.plan_qa.model import PlanStatus
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    Finding,
    Level,
)

CHECK_ID: Final[str] = "header-body-coherence"

_NON_TERMINAL_STATUSES: Final[frozenset[PlanStatus]] = frozenset(
    {PlanStatus.NOT_STARTED, PlanStatus.IN_PROGRESS}
)

_REMEDIATION: Final[str] = (
    "Flip the status header to `**Status**: Complete` (and move the plan to the "
    "archive directory per the plan lifecycle), or untick/remove the completion "
    "claims that contradict the current header."
)

# Plan 00341: a SECOND remediation, not a reworded first one. Telling the
# author of a half-delivered plan to mark it Complete would be actively wrong,
# which is why "started" and "finished" cannot share one message.
_STARTED_REMEDIATION: Final[str] = (
    "Flip the status header to `**Status**: In Progress`, or untick the boxes "
    "that contradict `Not Started`."
)


def _rule(context: CheckContext, target: DocumentTarget) -> list[Finding]:
    doc = target.doc
    if doc.status is None or doc.status not in _NON_TERMINAL_STATUSES:
        return []

    level = level_for_plan(context, target.plan_number)

    # Completion is checked FIRST because both branches match a `Not Started`
    # plan with every box ticked, and "you finished this" is the more useful
    # correction than "you started this".
    if doc.done_marker_count > 0 or doc.tasks.all_checked:
        return [
            Finding(
                check_id=CHECK_ID,
                level=level,
                message=(
                    f"PLAN.md header claims `{doc.status.value}` but the body claims completion"
                ),
                remediation=_REMEDIATION,
                path=target.rel_path,
            )
        ]

    # Plan 00341: a single ticked box falsifies "not started" on its own, with
    # no history needed to see it. The all-checked branch above cannot catch a
    # partially-delivered plan, which is exactly how a status header rots
    # behind shipped work.
    if doc.status is PlanStatus.NOT_STARTED and doc.tasks.checked > 0:
        return [
            Finding(
                check_id=CHECK_ID,
                level=level,
                message=(
                    "PLAN.md header claims `Not Started` but the body shows work already "
                    f"started ({doc.tasks.checked} of {doc.tasks.total_checkboxes} boxes ticked)"
                ),
                remediation=_STARTED_REMEDIATION,
                path=target.rel_path,
            )
        ]

    return []


CHECKS: Final[DocumentRuleChecks] = document_rule_checks(
    check_id=CHECK_ID,
    level=Level.BLOCK,
    sins=("A3", "A1"),
    rule=_rule,
)
