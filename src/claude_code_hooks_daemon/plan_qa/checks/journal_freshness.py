"""Check ``journal-freshness`` (Stage 3, advise; Plan 00163).

An In-Progress plan that already HAS a ``JOURNAL/`` whose newest day-file is
older than ``freshness_days`` is nagged to journal its recent activity.
Freshness reads the day-file NAME (``latest_journal_date``), never git dates,
so a journal edited but not yet committed still counts (Decision 8). Scoped to
plans that already journal — starting one is ``journal-folder-present``'s job.

``freshness_days`` (default 3) is deliberately shorter than the plan
``staleness_days`` (30): journals should nag sooner. ADVISE forever.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import journalling_active
from claude_code_hooks_daemon.plan_qa.model import (
    JOURNAL_BODY_FILE_HINT,
    PlanFolder,
    PlanLocation,
    PlanStatus,
    journal_append_command,
)
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "journal-freshness"


def _remediation(plan_dir: str) -> str:
    return (
        "For each listed plan, append an entry recording recent activity with "
        f"`{journal_append_command(plan_dir, None)}` ({JOURNAL_BODY_FILE_HINT})."
    )


def _run(context: CheckContext) -> list[Finding]:
    if context.tree is None or context.today is None or not journalling_active(context):
        return []

    stale: list[tuple[PlanFolder, int]] = []
    for folder in context.tree.folders:
        if folder.location != PlanLocation.ROOT:
            continue
        if folder.doc is None or folder.doc.status != PlanStatus.IN_PROGRESS:
            continue
        if not folder.has_journal or folder.latest_journal_date is None:
            continue
        days_stale = (context.today - folder.latest_journal_date).days
        if days_stale > context.journal_freshness_days:
            stale.append((folder, days_stale))

    if not stale:
        return []

    stale.sort(key=lambda item: item[1], reverse=True)
    lines = [f"- {folder.name}: {days} days since last journal entry" for folder, days in stale]
    message = "Plans whose JOURNAL/ has gone quiet (Plan 00163):\n" + "\n".join(lines)
    return [
        Finding(
            check_id=CHECK_ID,
            level=Level.ADVISE,
            message=message,
            remediation=_remediation(context.plan_dir_rel),
            path=None,
        )
    ]


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.SWEEP,
    level=Level.ADVISE,
    sins=(),
    run=_run,
)
