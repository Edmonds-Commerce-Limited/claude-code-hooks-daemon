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


def _rule(context: CheckContext, target: DocumentTarget) -> list[Finding]:
    doc = target.doc
    if doc.status not in _NON_TERMINAL_STATUSES:
        return []

    if doc.done_marker_count == 0 and not doc.tasks.all_checked:
        return []

    return [
        Finding(
            check_id=CHECK_ID,
            level=level_for_plan(context, target.plan_number),
            message=(f"PLAN.md header claims `{doc.status.value}` but the body claims completion"),
            remediation=_REMEDIATION,
            path=target.rel_path,
        )
    ]


CHECKS: Final[DocumentRuleChecks] = document_rule_checks(
    check_id=CHECK_ID,
    level=Level.BLOCK,
    sins=("A3", "A1"),
    rule=_rule,
)
