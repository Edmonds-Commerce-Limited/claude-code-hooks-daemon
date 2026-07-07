"""Check ``counter-sanity`` (Stage 2, block; sin D1).

A newly-staged plan folder whose number exceeds the git-anchored
``hooksdaemon.latestPlanNumber`` counter was not allocated via ``mkplan.bash``
— it either predates the counter's bootstrap or was hand-numbered, both of
which risk future numbering collisions.
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

CHECK_ID: Final[str] = "counter-sanity"

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
    if context.gitfacts is None:
        return []

    counter = context.gitfacts.plan_counter()
    if counter is None:
        return []

    findings: list[Finding] = []
    for number in sorted(_staged_new_plan_numbers(context)):
        if number <= counter:
            continue
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=level_for_plan(context, number),
                message=(
                    f"Plan folder {number:05d} exceeds the git-anchored counter "
                    f"(hooksdaemon.latestPlanNumber = {counter}), so it was not "
                    "allocated via mkplan.bash"
                ),
                remediation=(
                    "Recreate the plan folder via mkplan.bash (or reconcile the "
                    "counter if this number is genuinely sanctioned)."
                ),
            )
        )
    return findings


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.COMMIT,
    level=Level.BLOCK,
    sins=("D1",),
    run=_run,
)
