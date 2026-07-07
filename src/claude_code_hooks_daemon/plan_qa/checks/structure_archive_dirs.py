"""Check ``structure-archive-dirs`` (Stage 2/3, block; sin C3).

The plan directory needs a README index and a completed-plans archive to
function; a configured cancelled-plans archive is recommended but optional.
Folders that land outside the root and the archive directories, and stray
files at the plan root, are structural drift this check also surfaces.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.model import PlanLocation
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "structure-archive-dirs"

_OTHER_LOCATION_REMEDIATION: Final[str] = (
    "git mv this folder into the plan root or the matching archive directory."
)
_STRAY_FILE_REMEDIATION: Final[str] = (
    "Move this file into a plan folder, or relocate it to a docs location."
)


def _level(context: CheckContext, number: int) -> Level:
    return Level.ADVISE if number in context.legacy_plan_allowlist else Level.BLOCK


def _run(context: CheckContext) -> list[Finding]:
    if context.tree is None:
        return []

    tree = context.tree
    findings: list[Finding] = []

    if not tree.has_readme:
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.BLOCK,
                message=f"Plan directory {context.plan_dir_rel} has no README.md plan index",
                remediation=f"create {context.plan_dir_rel}/README.md",
                path=None,
            )
        )

    if not tree.has_completed_dir:
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.BLOCK,
                message=f"Plan directory {context.plan_dir_rel} has no {context.completed_dir} archive",
                remediation=f"mkdir {context.plan_dir_rel}/{context.completed_dir}/",
                path=None,
            )
        )

    if context.cancelled_dir is not None and not tree.has_cancelled_dir:
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.ADVISE,
                message=(
                    f"Plan directory {context.plan_dir_rel} has no {context.cancelled_dir} archive"
                ),
                remediation=f"mkdir {context.plan_dir_rel}/{context.cancelled_dir}/",
                path=None,
            )
        )

    for folder in tree.folders:
        if folder.location != PlanLocation.OTHER:
            continue
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=_level(context, folder.number),
                message=f"Plan folder {folder.name} sits outside the root and archive directories",
                remediation=_OTHER_LOCATION_REMEDIATION,
                path=folder.name,
            )
        )

    for stray in tree.stray_files:
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.ADVISE,
                message=f"Unexpected file {stray.name} at the plan root",
                remediation=_STRAY_FILE_REMEDIATION,
                path=stray.name,
            )
        )

    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=Stage.COMMIT, level=Level.BLOCK, sins=("C3",), run=_run),
    CheckSpec(check_id=CHECK_ID, stage=Stage.SWEEP, level=Level.BLOCK, sins=("C3",), run=_run),
)
