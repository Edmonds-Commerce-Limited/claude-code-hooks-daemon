"""Check ``task-grammar`` (Stage 1 + 3, advise; sin E6).

Ad-hoc progress markers (``[✓]``, ``[⏳]``, ``[~]``) are unparseable by
tooling that expects the template's checkbox + status-icon grammar. New
material is held to the block-level standard (via :func:`level_for_plan`);
existing files being edited for other reasons only get advice so a small
edit does not force a full grammar rewrite.

Registered at EDIT *and* SWEEP (Plan 00230). A sweep context has no
``file_exists_before``, so batch findings land at ADVISE — which is exactly
the intent: on-disk material is by definition not new.
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

CHECK_ID: Final[str] = "task-grammar"

_REMEDIATION: Final[str] = (
    "Use the template task grammar instead of ad-hoc markers like [✓], [⏳], "
    "[~]: `- [ ] ⬜ **Task N.N**: ...` for pending work, `- [x] ✅ ...` for done."
)


def _rule(context: CheckContext, target: DocumentTarget) -> list[Finding]:
    if target.doc.tasks.legacy_marker_lines == 0:
        return []

    level = (
        level_for_plan(context, target.plan_number)
        if context.file_exists_before is False
        else Level.ADVISE
    )

    return [
        Finding(
            check_id=CHECK_ID,
            level=level,
            message="PLAN.md uses ad-hoc legacy task markers instead of the template grammar",
            remediation=_REMEDIATION,
            path=target.rel_path,
        )
    ]


CHECKS: Final[DocumentRuleChecks] = document_rule_checks(
    check_id=CHECK_ID,
    level=Level.ADVISE,
    sins=("E6",),
    rule=_rule,
)
