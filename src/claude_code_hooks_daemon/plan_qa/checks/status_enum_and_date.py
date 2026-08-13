"""Check ``status-enum-and-date`` (Stage 1 + 3, block; sin A1).

A ``**Status**:`` line must parse to one of the allowed :class:`PlanStatus`
tokens, and — only when the project opts in via ``require_terminal_date``
— a terminal status must carry a ``(YYYY-MM-DD)`` qualifier. This repo's own
convention forbids completion dates, so ``require_terminal_date`` defaults
to ``False`` and the date finding never fires here.

Registered at EDIT *and* SWEEP (Plan 00230). An unparseable token is a pure
property of the document, so a write-time-only rule left every plan already on
disk unexamined — and an unparseable status is invisible to
``location-status-coherence``, whose terminal/non-terminal split a ``None``
status satisfies neither side of.
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

CHECK_ID: Final[str] = "status-enum-and-date"

_ALLOWED_TOKENS: Final[str] = (
    "Not Started, In Progress, Complete, Blocked, Cancelled, Superseded, Dormant"
)


def _rule(context: CheckContext, target: DocumentTarget) -> list[Finding]:
    if not target.doc.status_line_present:
        return []

    findings: list[Finding] = []

    if target.doc.status is None:
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=level_for_plan(context, target.plan_number),
                message=f"PLAN.md status value `{target.doc.status_raw}` is not a recognised token",
                remediation=f"Set `**Status**:` to one of the allowed tokens: {_ALLOWED_TOKENS}.",
                path=target.rel_path,
            )
        )
        return findings

    if context.require_terminal_date and target.doc.is_terminal and target.doc.status_date is None:
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=level_for_plan(context, target.plan_number),
                message="Terminal PLAN.md status is missing a completion date qualifier",
                remediation=(
                    f"Append a completion date to the status line, e.g. "
                    f"`**Status**: {target.doc.status.value} (YYYY-MM-DD)`."
                ),
                path=target.rel_path,
            )
        )

    return findings


CHECKS: Final[DocumentRuleChecks] = document_rule_checks(
    check_id=CHECK_ID,
    level=Level.BLOCK,
    sins=("A1",),
    rule=_rule,
)
