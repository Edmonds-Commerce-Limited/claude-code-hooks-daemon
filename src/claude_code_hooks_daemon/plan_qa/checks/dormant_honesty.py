"""Check ``dormant-honesty`` (Stage 3, advise; sin A6).

A plan still marked ``In Progress`` after twice the staleness window has
elapsed since its last commit is lying about its own activity level: nobody
is actually progressing it. This check names each such plan individually so
its header can be corrected to ``Dormant`` (with a reason) or resumed.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.model import PlanLocation, PlanStatus
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "dormant-honesty"

_DORMANT_THRESHOLD_MULTIPLIER: Final[int] = 2

_REMEDIATION: Final[str] = (
    "Change the header to `**Status**: Dormant` with a parenthetical naming "
    "what it is blocked on, or resume the work."
)


def _run(context: CheckContext) -> list[Finding]:
    if context.tree is None or context.gitfacts is None or context.today is None:
        return []

    threshold = _DORMANT_THRESHOLD_MULTIPLIER * context.staleness_days
    findings: list[Finding] = []
    for folder in context.tree.folders:
        if folder.location != PlanLocation.ROOT:
            continue
        if folder.doc is None or folder.doc.status != PlanStatus.IN_PROGRESS:
            continue
        rel = f"{context.plan_dir_rel}/{folder.name}"
        last = context.gitfacts.last_commit_date(rel)
        if last is None:
            continue
        days_stale = (context.today - last).days
        if days_stale > threshold:
            findings.append(
                Finding(
                    check_id=CHECK_ID,
                    level=Level.ADVISE,
                    message=(
                        f'{folder.name}: marked "In Progress" but has had no commit '
                        f"for {days_stale} days — this overstates activity"
                    ),
                    remediation=_REMEDIATION,
                    path=None,
                )
            )

    return findings


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.SWEEP,
    level=Level.ADVISE,
    sins=("A6",),
    run=_run,
)
