"""Check ``same-commit-plan-doc`` (Stage 2, advise; sins G1, E1).

A commit message that claims work on a plan number, alongside staged
``src/``, ``tests/`` or ``config/`` changes, but never touches that plan's
``PLAN.md``, leaves the plan document silently out of sync with the work it
describes.
"""

import re
from typing import Final

from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "same-commit-plan-doc"

_PLAN_REF_RE: Final[re.Pattern[str]] = re.compile(r"[Pp]lan\s+0*(\d{1,5})")
_CODE_PREFIXES: Final[tuple[str, ...]] = ("src/", "tests/", "config/")


def _run(context: CheckContext) -> list[Finding]:
    if context.commit_message is None or context.gitfacts is None:
        return []

    plan_numbers = {int(match) for match in _PLAN_REF_RE.findall(context.commit_message)}
    if not plan_numbers:
        return []

    staged_changes = context.gitfacts.staged_changes()
    touches_code = any(change.path.startswith(_CODE_PREFIXES) for change in staged_changes)
    if not touches_code:
        return []

    findings: list[Finding] = []
    for number in sorted(plan_numbers):
        plan_doc_re = re.compile(
            rf"^{re.escape(context.plan_dir_rel)}/(?:[^/]+/)?0*{number}-[^/]+/PLAN\.md$"
        )
        touches_plan_doc = any(
            plan_doc_re.match(change.path) or plan_doc_re.match(change.old_path or "")
            for change in staged_changes
        )
        if touches_plan_doc:
            continue
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.ADVISE,
                message=(
                    f"Commit claims work on Plan {number:05d} but does not " "update its PLAN.md"
                ),
                remediation=(
                    "Tick the tasks / update status in the plan document in " "this same commit."
                ),
            )
        )
    return findings


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.COMMIT,
    level=Level.ADVISE,
    sins=("G1", "E1"),
    run=_run,
)
