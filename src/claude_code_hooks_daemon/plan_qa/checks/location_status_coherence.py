"""Check ``location-status-coherence`` (Stage 2/3, block; sins A1, A5, C1, C2, E8).

Ties a plan folder's physical location to what its own PLAN.md claims: a
missing document is a structural gap, a terminal status loitering in the
active root means the archive move never happened, and a non-terminal
status inside an archive directory means the header was never updated
before (or after) the move.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.model import (
    PlanDoc,
    PlanFolder,
    PlanLocation,
    PlanStatus,
)
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "location-status-coherence"

_MISSING_PLAN_MD_REMEDIATION: Final[str] = "Add a PLAN.md with at least a status header."
_MISSING_STATUS_LINE_MESSAGE: Final[str] = "PLAN.md has no parseable `**Status**:` line"
_MISSING_STATUS_LINE_REMEDIATION: Final[str] = (
    "Add a status header line, e.g. `**Status**: In Progress`."
)
_STALE_ARCHIVED_HEADER_REMEDIATION: Final[str] = (
    "Correct the archived plan's status header to its true terminal state."
)

_ARCHIVED_LOCATIONS: Final[frozenset[PlanLocation]] = frozenset(
    {PlanLocation.COMPLETED, PlanLocation.CANCELLED}
)
_NON_TERMINAL_STATUSES: Final[frozenset[PlanStatus]] = frozenset(
    {PlanStatus.NOT_STARTED, PlanStatus.IN_PROGRESS}
)


def _level(context: CheckContext, number: int) -> Level:
    return Level.ADVISE if number in context.legacy_plan_allowlist else Level.BLOCK


def _archive_dir_for(context: CheckContext, doc: PlanDoc) -> str:
    if doc.status == PlanStatus.CANCELLED and context.cancelled_dir is not None:
        return context.cancelled_dir
    return context.completed_dir


def _folder_findings(context: CheckContext, folder: PlanFolder) -> list[Finding]:
    if not folder.has_plan_md:
        return [
            Finding(
                check_id=CHECK_ID,
                level=_level(context, folder.number),
                message=f"Plan folder {folder.name} has no PLAN.md",
                remediation=_MISSING_PLAN_MD_REMEDIATION,
                path=folder.name,
            )
        ]

    doc = folder.doc
    assert doc is not None  # has_plan_md implies doc was parsed
    findings: list[Finding] = []

    if not doc.status_line_present:
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.ADVISE,
                message=_MISSING_STATUS_LINE_MESSAGE,
                remediation=_MISSING_STATUS_LINE_REMEDIATION,
                path=folder.name,
            )
        )

    if doc.is_terminal and folder.location == PlanLocation.ROOT:
        archive_dir = _archive_dir_for(context, doc)
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=_level(context, folder.number),
                message=(
                    f"Plan folder {folder.name} has a terminal status "
                    f"({doc.status.value if doc.status else 'unknown'}) but is still in the active root"
                ),
                remediation=(
                    f"git mv {context.plan_dir_rel}/{folder.name} "
                    f"{context.plan_dir_rel}/{archive_dir}/ and update the README row/stats."
                ),
                path=folder.name,
            )
        )

    if doc.status in _NON_TERMINAL_STATUSES and folder.location in _ARCHIVED_LOCATIONS:
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.ADVISE,
                message=(
                    f"Plan folder {folder.name} is archived but its status header "
                    f"reads {doc.status.value}"
                ),
                remediation=_STALE_ARCHIVED_HEADER_REMEDIATION,
                path=folder.name,
            )
        )

    return findings


def _run(context: CheckContext) -> list[Finding]:
    if context.tree is None:
        return []

    findings: list[Finding] = []
    for folder in context.tree.folders:
        if folder.location == PlanLocation.OTHER:
            continue
        findings.extend(_folder_findings(context, folder))
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    CheckSpec(
        check_id=CHECK_ID,
        stage=Stage.COMMIT,
        level=Level.BLOCK,
        sins=("A1", "A5", "C1", "C2", "E8"),
        run=_run,
    ),
    CheckSpec(
        check_id=CHECK_ID,
        stage=Stage.SWEEP,
        level=Level.BLOCK,
        sins=("A1", "A5", "C1", "C2", "E8"),
        run=_run,
    ),
)
