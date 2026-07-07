"""Check ``terminal-state-atomic`` (Stage 2, block; sins C1, C2, C3, B3).

A commit that flips a plan's status to a terminal state (Complete, Cancelled,
Superseded) must, in the SAME commit, relocate the folder to the archive
directory and update the README index. Splitting the flip and the move
across commits leaves a window where the plan is terminal but still lives —
and is indexed — as active.
"""

import re
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import level_for_plan
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts, StagedChange
from claude_code_hooks_daemon.plan_qa.model import PlanDoc, PlanStatus
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "terminal-state-atomic"

_NEW_OR_MODIFIED_STATUSES: Final[tuple[str, ...]] = ("A", "M")
_RENAME_STATUS_PREFIX: Final[str] = "R"
_PLAN_MD_SUFFIX: Final[str] = "/PLAN.md"
_README_FILENAME: Final[str] = "README.md"
_PLAN_FOLDER_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{1,5})-[A-Za-z][^/]*$")


def _readme_path(context: CheckContext) -> str:
    return f"{context.plan_dir_rel.rstrip('/')}/{_README_FILENAME}"


def _readme_staged(gitfacts: GitFacts, context: CheckContext) -> bool:
    readme_path = _readme_path(context)
    return any(change.path == readme_path for change in gitfacts.staged_changes())


def _root_plan_folder(path: str, plan_dir_rel: str) -> str | None:
    """Folder name when ``path`` is a PLAN.md directly under the plan root."""
    prefix = plan_dir_rel.rstrip("/") + "/"
    if not path.startswith(prefix) or not path.endswith(_PLAN_MD_SUFFIX):
        return None
    remainder = path[len(prefix) : -len(_PLAN_MD_SUFFIX)]
    if "/" in remainder or not _PLAN_FOLDER_NUMBER_RE.match(remainder):
        return None
    return remainder


def _archive_dir_component(path: str, context: CheckContext) -> str | None:
    """First path component when ``path`` is a PLAN.md under an archive dir."""
    prefix = context.plan_dir_rel.rstrip("/") + "/"
    if not path.startswith(prefix) or not path.endswith(_PLAN_MD_SUFFIX):
        return None
    remainder = path[len(prefix) :]
    parts = remainder.split("/")
    if len(parts) < 2:
        return None
    archive_dirs = {context.completed_dir}
    if context.cancelled_dir is not None:
        archive_dirs.add(context.cancelled_dir)
    return parts[0] if parts[0] in archive_dirs else None


def _archive_dir_for_status(context: CheckContext, status: PlanStatus | None) -> str:
    if status == PlanStatus.CANCELLED and context.cancelled_dir is not None:
        return context.cancelled_dir
    return context.completed_dir


def _flip_finding(
    gitfacts: GitFacts, context: CheckContext, change: StagedChange, folder: str
) -> Finding | None:
    staged_text = gitfacts.staged_file_text(change.path)
    if staged_text is None:
        return None
    staged_doc = PlanDoc.parse(staged_text)
    if not staged_doc.is_terminal:
        return None

    head_path = change.old_path or change.path
    head_text = gitfacts.head_file_text(head_path)
    flip = head_text is None or not PlanDoc.parse(head_text).is_terminal
    if not flip:
        return None

    archive_dir = _archive_dir_for_status(context, staged_doc.status)
    todo = [
        f"`git mv {context.plan_dir_rel}/{folder} {context.plan_dir_rel}/{archive_dir}/{folder}`"
    ]
    if not _readme_staged(gitfacts, context):
        todo.append("update the README row (move to the matching section) and statistics")

    return Finding(
        check_id=CHECK_ID,
        level=level_for_plan(context, staged_doc.plan_number),
        message=(
            f"Plan {folder} flips to a terminal status in this commit but its "
            "folder is still staged under the plan root"
        ),
        remediation="; ".join(todo),
        path=change.path,
    )


def _move_without_readme_finding(
    gitfacts: GitFacts, context: CheckContext, change: StagedChange, archive_component: str
) -> Finding | None:
    if _readme_staged(gitfacts, context):
        return None
    staged_text = gitfacts.staged_file_text(change.path)
    plan_number = PlanDoc.parse(staged_text).plan_number if staged_text is not None else None
    return Finding(
        check_id=CHECK_ID,
        level=level_for_plan(context, plan_number),
        message=(
            f"{change.path} is moved into {archive_component}/ in this commit "
            "but the README index is not updated"
        ),
        remediation=(
            "Update the README row (move to the matching section) and statistics "
            "in this same commit."
        ),
        path=change.path,
    )


def _run(context: CheckContext) -> list[Finding]:
    gitfacts = context.gitfacts
    if gitfacts is None:
        return []

    findings: list[Finding] = []
    for change in gitfacts.staged_changes():
        is_new_or_renamed = change.status in _NEW_OR_MODIFIED_STATUSES or change.status.startswith(
            _RENAME_STATUS_PREFIX
        )
        if not is_new_or_renamed:
            continue

        folder = _root_plan_folder(change.path, context.plan_dir_rel)
        if folder is not None:
            finding = _flip_finding(gitfacts, context, change, folder)
            if finding is not None:
                findings.append(finding)
            continue

        if change.status.startswith(_RENAME_STATUS_PREFIX):
            archive_component = _archive_dir_component(change.path, context)
            if archive_component is not None:
                finding = _move_without_readme_finding(gitfacts, context, change, archive_component)
                if finding is not None:
                    findings.append(finding)

    return findings


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.COMMIT,
    level=Level.BLOCK,
    sins=("C1", "C2", "C3", "B3"),
    run=_run,
)
