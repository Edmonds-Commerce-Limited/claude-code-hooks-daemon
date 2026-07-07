"""Check ``terminal-placement-hint`` (Stage 1, advise; sins C1, C2, C3).

A plan whose header has already flipped to a terminal status but whose
folder is still sitting in the active root is a plan the reader has to
double-check every time: the archive move is the signal that a plan is
truly finished, and it should land in the SAME commit as the status flip.
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

CHECK_ID: Final[str] = "terminal-placement-hint"


def _run(context: CheckContext) -> list[Finding]:
    target = edit_target(context)
    if target is None or not target.doc.is_terminal or target.in_archive:
        return []

    is_cancelled = target.doc.status is not None and target.doc.status.value == "Cancelled"
    archive_dir = (
        (context.cancelled_dir or context.completed_dir) if is_cancelled else context.completed_dir
    )

    remediation = (
        f"In the same commit, `git mv` the plan folder into {archive_dir}/ "
        "(or the configured cancelled directory for cancelled plans) and update "
        "the plan README row and statistics."
    )

    return [
        Finding(
            check_id=CHECK_ID,
            level=Level.ADVISE,
            message="PLAN.md has a terminal status but its folder is still in the active plan root",
            remediation=remediation,
            path=target.rel_path,
        )
    ]


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.EDIT,
    level=Level.ADVISE,
    sins=("C1", "C2", "C3"),
    run=_run,
)
