"""Check ``journal-folder-present`` (Stage 3, advise; Plan 00163).

An In-Progress plan numbered at/after ``grandfather_before`` that has no
``JOURNAL/`` directory is nagged to start journalling. Scoped to In Progress
only (mirrors ``staleness-nag``): Not Started is an honest backlog, and
Blocked/Dormant are already-declared inactivity — nagging those would train
users to ignore the sweep.

Grandfathering (Decision 7): the ~160 journal-less legacy plans below the
threshold are never nagged (no backfill). ADVISE forever.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import journalling_active
from claude_code_hooks_daemon.plan_qa.model import PlanFolder, PlanLocation, PlanStatus
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "journal-folder-present"

_REMEDIATION: Final[str] = (
    "Start a journal for each listed plan: create "
    "`{plan}/JOURNAL/NNNNN-Journal-YY-MM-DD.md` (mkplan.bash scaffolds it for "
    "new plans) and log activity as you work. See CLAUDE/PlanJournalling.md."
)


def _run(context: CheckContext) -> list[Finding]:
    if context.tree is None or not journalling_active(context):
        return []

    missing: list[PlanFolder] = [
        folder
        for folder in context.tree.folders
        if folder.location == PlanLocation.ROOT
        and folder.doc is not None
        and folder.doc.status == PlanStatus.IN_PROGRESS
        and folder.number >= context.journal_grandfather_before
        and not folder.has_journal
    ]
    if not missing:
        return []

    missing.sort(key=lambda folder: folder.number)
    lines = [f"- {folder.name}" for folder in missing]
    message = "Active plans with no JOURNAL/ (Plan 00163):\n" + "\n".join(lines)
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
    sins=(),
    run=_run,
)
