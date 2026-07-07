"""Check ``staleness-nag`` (Stage 3, advise; sins A4, A6, E3).

Active (non-terminal) plans that have had no commit activity for longer than
the configured staleness window are quietly rotting: nobody has touched them,
but nothing in the tree says so. This check names them, ranked most-stale
first, so a session can decide to keep, mark Dormant, or cancel each one.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.model import PlanFolder, PlanLocation
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "staleness-nag"

_REMEDIATION: Final[str] = (
    "For each listed plan: confirm it is still active, mark it "
    "`**Status**: Dormant` naming what it is blocked on, or cancel it."
)


def _run(context: CheckContext) -> list[Finding]:
    if context.tree is None or context.gitfacts is None or context.today is None:
        return []

    stale: list[tuple[PlanFolder, int]] = []
    for folder in context.tree.folders:
        if folder.location != PlanLocation.ROOT:
            continue
        if folder.doc is None or folder.doc.is_terminal:
            continue
        rel = f"{context.plan_dir_rel}/{folder.name}"
        last = context.gitfacts.last_commit_date(rel)
        if last is None:
            continue
        days_stale = (context.today - last).days
        if days_stale > context.staleness_days:
            stale.append((folder, days_stale))

    if not stale:
        return []

    stale.sort(key=lambda item: item[1], reverse=True)
    lines = [f"- {folder.name}: {days} days since last commit" for folder, days in stale]
    message = "Stale plans with no recent activity:\n" + "\n".join(lines)

    return [
        Finding(
            check_id=CHECK_ID,
            level=Level.ADVISE,
            message=message,
            remediation=_REMEDIATION,
            path=None,
        )
    ]


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.SWEEP,
    level=Level.ADVISE,
    sins=("A4", "A6", "E3"),
    run=_run,
)
