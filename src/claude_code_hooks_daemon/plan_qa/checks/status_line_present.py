"""Check ``status-line-present`` (Stage 1 + 3, block; sins A2, E8).

A PLAN.md must contain a parseable ``**Status**:`` line. Without one the plan
has no machine-readable state at all — the root enabler of "finished work
marked Not Started" rot: tooling and humans both fall back to guessing from
prose. Registered at EDIT *and* SWEEP (Plan 00230), because a document with no
status line is exactly as unreadable whether it was just written or has been
sitting on disk for a year.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    DocumentRuleChecks,
    DocumentTarget,
    document_rule_checks,
    level_for_plan,
)
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    Finding,
    Level,
)

CHECK_ID: Final[str] = "status-line-present"

_REMEDIATION: Final[str] = (
    "Add a status header line to the document, e.g. `**Status**: Not Started` "
    "(allowed tokens: Not Started, In Progress, Complete, Blocked, Cancelled, "
    "Superseded, Dormant)."
)


def _rule(context: CheckContext, target: DocumentTarget) -> list[Finding]:
    if target.doc.status_line_present:
        return []
    return [
        Finding(
            check_id=CHECK_ID,
            level=level_for_plan(context, target.plan_number),
            message="PLAN.md has no parseable `**Status**:` line",
            remediation=_REMEDIATION,
            path=target.rel_path,
        )
    ]


CHECKS: Final[DocumentRuleChecks] = document_rule_checks(
    check_id=CHECK_ID,
    level=Level.BLOCK,
    sins=("A2", "E8"),
    rule=_rule,
)
