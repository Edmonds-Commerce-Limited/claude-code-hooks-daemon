"""Check ``template-metadata`` (Stage 1, advise; sin E7).

Brand-new plan documents should carry the full template header block
(Created/Owner/Priority) so the plan index and reviewers have the context
they need. This is advisory only: legacy plans predating the template are
never re-checked because the check only applies when the file is new.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import edit_target
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "template-metadata"

_REMEDIATION: Final[str] = (
    "Add the missing template header line(s), e.g. `**Created**: YYYY-MM-DD`, "
    "`**Owner**: <name>`, `**Priority**: High|Medium|Low`."
)


def _run(context: CheckContext) -> list[Finding]:
    if context.file_exists_before is not False:
        return []

    target = edit_target(context)
    if target is None:
        return []

    doc = target.doc
    missing: list[str] = []
    if doc.created is None:
        missing.append("Created")
    if doc.owner is None:
        missing.append("Owner")
    if doc.priority is None:
        missing.append("Priority")

    if not missing:
        return []

    return [
        Finding(
            check_id=CHECK_ID,
            level=Level.ADVISE,
            message=f"New PLAN.md is missing template header field(s): {', '.join(missing)}",
            remediation=_REMEDIATION,
            path=target.rel_path,
        )
    ]


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.EDIT,
    level=Level.ADVISE,
    sins=("E7",),
    run=_run,
)
