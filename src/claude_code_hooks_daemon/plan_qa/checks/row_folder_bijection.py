"""Check ``row-folder-bijection`` (Stage 2/3, block; sins B1, B2, B7).

A plan folder and its README index row are two views of the same fact; this
check enforces the bijection between them: every folder has a row in an
acceptable section, every linked row resolves to a real folder, and every
row's number has a folder somewhere on disk.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.model import PlanFolder, PlanLocation, PlanTree
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex, ReadmeRow, ReadmeSection
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "row-folder-bijection"

_LOCATION_SECTIONS: Final[dict[PlanLocation, frozenset[ReadmeSection]]] = {
    PlanLocation.ROOT: frozenset({ReadmeSection.ACTIVE, ReadmeSection.BLOCKED}),
    PlanLocation.COMPLETED: frozenset({ReadmeSection.COMPLETED, ReadmeSection.CANCELLED}),
    PlanLocation.CANCELLED: frozenset({ReadmeSection.CANCELLED}),
}

_UNINDEXED_REMEDIATION: Final[str] = (
    "Add an index row linking to this plan in the appropriate README section."
)
_WRONG_SECTION_REMEDIATION: Final[str] = (
    "Move the README row to the matching section (or move the folder to match its row)."
)
_BROKEN_LINK_REMEDIATION: Final[str] = (
    "Fix the link path in the README row, or create the target plan folder."
)
_ORPHAN_ROW_REMEDIATION: Final[str] = (
    "Create the missing plan folder, or remove the stale README row."
)


def _level(context: CheckContext, number: int | None) -> Level:
    if number is not None and number in context.legacy_plan_allowlist:
        return Level.ADVISE
    return Level.BLOCK


def _folder_findings(context: CheckContext, folder: PlanFolder) -> list[Finding]:
    rows = context.readme.rows_for(folder.number) if context.readme is not None else ()
    level = _level(context, folder.number)

    if not rows:
        return [
            Finding(
                check_id=CHECK_ID,
                level=level,
                message=f"Plan folder {folder.name} has no README index row",
                remediation=_UNINDEXED_REMEDIATION,
                path=folder.name,
            )
        ]

    acceptable = _LOCATION_SECTIONS[folder.location]
    if any(row.section in acceptable for row in rows):
        return []

    actual = sorted({row.section.value for row in rows})
    expected = sorted(section.value for section in acceptable)
    return [
        Finding(
            check_id=CHECK_ID,
            level=level,
            message=(
                f"Plan folder {folder.name} is indexed under section(s) {actual} "
                f"but its location expects one of {expected}"
            ),
            remediation=_WRONG_SECTION_REMEDIATION,
            path=folder.name,
        )
    ]


def _link_findings(context: CheckContext, row: ReadmeRow) -> list[Finding]:
    if row.link is None:
        return []
    target_parent = (context.plan_dir / row.link).parent
    if target_parent.is_dir():
        return []
    number = row.numbers[0] if row.numbers else None
    return [
        Finding(
            check_id=CHECK_ID,
            level=_level(context, number),
            message=f"README row link `{row.link}` points at a folder that does not exist",
            remediation=_BROKEN_LINK_REMEDIATION,
            path=row.link,
        )
    ]


def _orphan_row_findings(
    context: CheckContext, tree: PlanTree, readme: ReadmeIndex
) -> list[Finding]:
    folder_numbers = {folder.number for folder in tree.folders}
    findings: list[Finding] = []
    for number in sorted(readme.numbers()):
        if number in folder_numbers:
            continue
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=_level(context, number),
                message=f"README indexes plan {number:05d} but no folder exists for that plan",
                remediation=_ORPHAN_ROW_REMEDIATION,
                path=None,
            )
        )
    return findings


def _run(context: CheckContext) -> list[Finding]:
    if context.tree is None or context.readme is None:
        return []

    findings: list[Finding] = []
    for folder in context.tree.folders:
        if folder.location == PlanLocation.OTHER:
            continue
        findings.extend(_folder_findings(context, folder))

    for row in context.readme.rows:
        findings.extend(_link_findings(context, row))

    findings.extend(_orphan_row_findings(context, context.tree, context.readme))
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    CheckSpec(
        check_id=CHECK_ID,
        stage=Stage.COMMIT,
        level=Level.BLOCK,
        sins=("B1", "B2", "B7"),
        run=_run,
    ),
    CheckSpec(
        check_id=CHECK_ID,
        stage=Stage.SWEEP,
        level=Level.BLOCK,
        sins=("B1", "B2", "B7"),
        run=_run,
    ),
)
