"""Check ``no-new-collisions`` (Stage 2/3, block; sin D1).

Two plan folders must never claim the same plan number: whichever tool wrote
the second one skipped the git-counter allocation and silently shadows the
first. This is the plan's canonical "full-tree-consistency" example — the
same rule runs at commit time (catch it before it lands) and at sweep time
(catch drift that slipped through some other path).
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "no-new-collisions"

_REMEDIATION: Final[str] = (
    "Renumber the newest folder via the git counter / mkplan.bash and update its README row."
)


def _run(context: CheckContext) -> list[Finding]:
    if context.tree is None:
        return []

    findings: list[Finding] = []
    for number, claimants in sorted(context.tree.collisions().items()):
        if number in context.collision_allowlist:
            continue
        level = Level.ADVISE if number in context.legacy_plan_allowlist else Level.BLOCK
        names = ", ".join(sorted(folder.name for folder in claimants))
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=level,
                message=f"Plan number {number:05d} is claimed by multiple folders: {names}",
                remediation=_REMEDIATION,
                path=None,
            )
        )
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=Stage.COMMIT, level=Level.BLOCK, sins=("D1",), run=_run),
    CheckSpec(check_id=CHECK_ID, stage=Stage.SWEEP, level=Level.BLOCK, sins=("D1",), run=_run),
)
