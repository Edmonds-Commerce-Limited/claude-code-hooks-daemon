"""Check ``status-line-present`` (Stage 1, block; sins A2, E8).

A PLAN.md being written must contain a parseable ``**Status**:`` line.
Without one the plan has no machine-readable state at all — the root
enabler of "finished work marked Not Started" rot: tooling and humans both
fall back to guessing from prose.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import edit_target, level_for_plan
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "status-line-present"

_REMEDIATION: Final[str] = (
    "Add a status header line to the document, e.g. `**Status**: Not Started` "
    "(allowed tokens: Not Started, In Progress, Complete, Blocked, Cancelled, "
    "Superseded, Dormant)."
)


def _run(context: CheckContext) -> list[Finding]:
    target = edit_target(context)
    if target is None or target.doc.status_line_present:
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


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.EDIT,
    level=Level.BLOCK,
    sins=("A2", "E8"),
    run=_run,
)
