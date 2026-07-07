"""Check ``stats-recount`` (Stage 2/3, block; sin B5).

The README's statistics bullets are hand-maintained numbers that drift the
moment a plan is created, moved, or cancelled without updating them. This
check recounts the tree and compares: an undercounted "Total" (a high-water
"plans ever created" figure legitimately exceeds folders on disk) blocks,
while the more volatile per-category figures are advisory only.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.model import PlanLocation
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "stats-recount"

_TOTAL_KEYWORD: Final[str] = "total"
_CATEGORY_KEYWORDS: Final[tuple[str, ...]] = ("active", "completed", "cancelled")

_TOTAL_REMEDIATION: Final[str] = (
    "Update the statistics section — the Total figure undercounts plan folders on disk."
)
_CATEGORY_REMEDIATION: Final[str] = "Update the statistics section with the recounted figure."


def _tree_counts(context: CheckContext) -> dict[str, int]:
    tree = context.tree
    assert tree is not None  # narrowed by caller
    return {
        "total": len(tree.folders),
        "active": sum(1 for folder in tree.folders if folder.location == PlanLocation.ROOT),
        "completed": sum(1 for folder in tree.folders if folder.location == PlanLocation.COMPLETED),
        "cancelled": sum(1 for folder in tree.folders if folder.location == PlanLocation.CANCELLED),
    }


def _run(context: CheckContext) -> list[Finding]:
    if context.tree is None or context.readme is None or not context.readme.stats:
        return []

    counts = _tree_counts(context)
    findings: list[Finding] = []

    for label, value in context.readme.stats.items():
        lowered = label.lower()
        if _TOTAL_KEYWORD in lowered:
            if value < counts["total"]:
                findings.append(
                    Finding(
                        check_id=CHECK_ID,
                        level=Level.BLOCK,
                        message=(
                            f"Statistics label `{label}` states {value} but {counts['total']} "
                            "plan folders exist on disk"
                        ),
                        remediation=_TOTAL_REMEDIATION,
                        path=None,
                    )
                )
            continue

        for keyword in _CATEGORY_KEYWORDS:
            if keyword in lowered:
                recounted = counts[keyword]
                if value != recounted:
                    findings.append(
                        Finding(
                            check_id=CHECK_ID,
                            level=Level.ADVISE,
                            message=(
                                f"Statistics label `{label}` states {value} but the recounted "
                                f"value is {recounted}"
                            ),
                            remediation=_CATEGORY_REMEDIATION,
                            path=None,
                        )
                    )
                break

    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=Stage.COMMIT, level=Level.BLOCK, sins=("B5",), run=_run),
    CheckSpec(check_id=CHECK_ID, stage=Stage.SWEEP, level=Level.BLOCK, sins=("B5",), run=_run),
)
