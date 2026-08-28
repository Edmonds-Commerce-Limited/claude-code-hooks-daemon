"""Check ``archived-status-coherence`` (Stage 2, block; sins C1, C2).

Fills a gap ``location-status-coherence``'s COMMIT-stage registration cannot
reach: it reads ``context.tree``, which ``staged_context()`` builds by
scanning the WORKTREE filesystem — never the staged git blob. ``git mv``
stages a rename using the INDEX's existing content, so if a status flip to a
terminal value was made in the worktree but never re-``git add``ed, the
STAGED blob at the new (archived) path can still read a non-terminal status
even though the worktree file already shows the fix, and the worktree-based
check sees only the (correct-looking) worktree file. This check reads the
STAGED content directly (``GitFacts.staged_file_text``), independent of what
is currently on disk, so a commit that would actually land an archived plan
with a non-terminal or unparseable status header is caught before it lands.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import level_for_plan
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts, StagedChange
from claude_code_hooks_daemon.plan_qa.model import PlanDoc
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "archived-status-coherence"

_PLAN_MD_SUFFIX: Final[str] = "/PLAN.md"
_RELEVANT_STATUSES: Final[tuple[str, ...]] = ("A", "M")
_RENAME_STATUS_PREFIX: Final[str] = "R"
_UNKNOWN_STATUS_LABEL: Final[str] = "unknown/unparseable"

_REMEDIATION: Final[str] = (
    "Re-stage the moved PLAN.md (`git add`) so its terminal status is part of "
    "this commit, or correct the status header to its true terminal state."
)


def _archive_dir_for_path(path: str, context: CheckContext) -> str | None:
    """First path component when ``path`` is a staged PLAN.md under an archive dir."""
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


def _finding_for_change(
    gitfacts: GitFacts, context: CheckContext, change: StagedChange, archive_dir: str
) -> Finding | None:
    staged_text = gitfacts.staged_file_text(change.path)
    if staged_text is None:
        return None
    staged_doc = PlanDoc.parse(staged_text)
    if staged_doc.is_terminal:
        return None

    status_desc = staged_doc.status.value if staged_doc.status else _UNKNOWN_STATUS_LABEL
    return Finding(
        check_id=CHECK_ID,
        level=level_for_plan(context, staged_doc.plan_number),
        message=(
            f"{change.path} is staged under {archive_dir}/ but its STAGED "
            f"content's status header reads {status_desc}, not a terminal status"
        ),
        remediation=_REMEDIATION,
        path=change.path,
    )


def _run(context: CheckContext) -> list[Finding]:
    gitfacts = context.gitfacts
    if gitfacts is None:
        return []

    findings: list[Finding] = []
    for change in gitfacts.staged_changes():
        is_relevant = change.status in _RELEVANT_STATUSES or change.status.startswith(
            _RENAME_STATUS_PREFIX
        )
        if not is_relevant:
            continue
        archive_dir = _archive_dir_for_path(change.path, context)
        if archive_dir is None:
            continue
        finding = _finding_for_change(gitfacts, context, change, archive_dir)
        if finding is not None:
            findings.append(finding)
    return findings


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.COMMIT,
    level=Level.BLOCK,
    sins=("C1", "C2"),
    run=_run,
)
