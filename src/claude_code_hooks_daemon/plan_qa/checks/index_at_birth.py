"""Check ``index-at-birth`` (Stage 2, block; sins B1, B2, D2, G2).

A commit that creates a new plan folder must also stage the README index row
for it. Without this, a plan can exist on disk indefinitely with no entry in
the index a human or the numbering tooling would ever consult.
"""

import re
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import level_for_plan
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "index-at-birth"

_NEW_STATUS: Final[str] = "A"
_PLAN_FOLDER_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{1,5})-[A-Za-z]")


def _staged_new_plan_numbers(context: CheckContext) -> frozenset[int]:
    """Distinct plan numbers of newly-staged plan folders under the plan dir."""
    assert context.gitfacts is not None
    prefix = context.plan_dir_rel.rstrip("/") + "/"
    numbers: set[int] = set()
    for change in context.gitfacts.staged_changes():
        if change.status != _NEW_STATUS or not change.path.startswith(prefix):
            continue
        remainder = change.path[len(prefix) :]
        first_component = remainder.split("/", 1)[0]
        match = _PLAN_FOLDER_NUMBER_RE.match(first_component)
        if match:
            numbers.add(int(match.group(1)))
    return frozenset(numbers)


def _run(context: CheckContext) -> list[Finding]:
    if context.gitfacts is None or context.readme is None:
        return []

    indexed = context.readme.numbers()
    findings: list[Finding] = []
    for number in sorted(_staged_new_plan_numbers(context)):
        if number in indexed:
            continue
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=level_for_plan(context, number),
                message=(
                    f"Commit creates plan folder {number:05d} but stages no "
                    "README index row for it"
                ),
                remediation=(
                    f"Add a row for {number:05d} under Active Plans in "
                    f"{context.plan_dir_rel}/README.md in this same commit."
                ),
            )
        )
    return findings


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.COMMIT,
    level=Level.BLOCK,
    sins=("B1", "B2", "D2", "G2"),
    run=_run,
)
