"""Check ``same-commit-plan-doc`` (Stage 2; sins G1, E1).

A commit message that claims work on a plan number, alongside staged
``src/``, ``tests/`` or ``config/`` changes, but never touches that plan's
``PLAN.md``, leaves the plan document silently out of sync with the work it
describes.

**Plan 00341 Phase 2 added a second, stronger assertion.** Touching
``PLAN.md`` satisfied the original check, so a commit that added a paragraph
and left the header at ``Not Started`` passed — and that is the shape that
actually rots: Plan 00110 sat at ``Not Started`` with 8 of 60 tasks done. The
content assertion is that a plan cannot still be ``Not Started`` once code
ships for it. It costs nothing extra, because the staged blob is already in
hand.

The two findings differ in level, and deliberately:

- **BLOCK** for the content assertion. It is a self-contradiction with a
  one-word fix, and the ADVISE that already existed was measurably not enough
  — it fired on ``923fd583`` and the plan stayed ``Not Started`` for five days.
- **ADVISE** for the original "PLAN.md untouched". Its remediation is "tick
  the tasks", which is a judgement rather than a contradiction.

**The BLOCK is scoped to plan numbers named in the SUBJECT line, and that
scoping was measured rather than assumed.** Over this repository's last 250
commits an unscoped rule fired 4 times, and one was a commit that merely
REFERENCED another plan while delivering a different one — a 25% false
positive rate, fatal for a BLOCK. Subject-scoping left 2 fires, both genuine.
A plan named only in the body is a reference; a plan named in the subject is a
claim of delivery.
"""

import re
from typing import Final

from claude_code_hooks_daemon.core.project_layout import main_repo_code_dirs
from claude_code_hooks_daemon.plan_qa.model import PlanDoc, PlanStatus
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "same-commit-plan-doc"

_PLAN_REF_RE: Final[re.Pattern[str]] = re.compile(r"[Pp]lan\s+0*(\d{1,5})")


def _plan_status(
    context: CheckContext, plan_doc_re: re.Pattern[str], number: int
) -> PlanStatus | None:
    """Status of plan ``number``, read from the STAGED blob where one exists.

    Staged first, and that is what makes the remediation satisfiable: the fix
    is "flip the status in this same commit", so reading HEAD would reject the
    author for doing exactly what they were told.

    Args:
        context: The check context (gitfacts and project root).
        plan_doc_re: Matcher for this plan's ``PLAN.md`` path.
        number: The plan number.

    Returns:
        The parsed status, or None when no ``PLAN.md`` can be found or read --
        a plan number with no document cannot have a status, and inventing one
        would turn a typo in a commit message into a blocked commit.
    """
    gitfacts = context.gitfacts
    if gitfacts is None:
        return None
    for change in gitfacts.staged_changes():
        if plan_doc_re.match(change.path):
            text = gitfacts.staged_file_text(change.path)
            return PlanDoc.parse(text).status if text is not None else None

    plan_dir = context.project_root / context.plan_dir_rel
    for candidate in sorted(plan_dir.glob(f"**/{number:05d}-*/PLAN.md")):
        try:
            return PlanDoc.parse(candidate.read_text(encoding="utf-8")).status
        except (OSError, UnicodeDecodeError):
            # Both halves are "this document cannot be read", which the
            # docstring above already answers with None. UnicodeDecodeError is
            # a ValueError, so an OSError-only clause let a non-UTF-8 PLAN.md
            # raise straight out of the commit gate (Plan 00364 Task 2.4).
            return None
    return None


def _run(context: CheckContext) -> list[Finding]:
    if context.commit_message is None or context.gitfacts is None:
        return []

    plan_numbers = {int(match) for match in _PLAN_REF_RE.findall(context.commit_message)}
    if not plan_numbers:
        return []
    # Subject line only for the BLOCK -- see the module docstring for the
    # measurement that forced this scoping.
    subject = context.commit_message.splitlines()[0] if context.commit_message else ""
    delivered_numbers = {int(match) for match in _PLAN_REF_RE.findall(subject)}

    # "Main repo code dirs" read from the ProjectLayout facade (Plan 00288
    # Task 4.3/C5) instead of the hardcoded src/tests/config triple.
    code_prefixes = tuple(f"{d}/" for d in main_repo_code_dirs(context.layout))
    staged_changes = context.gitfacts.staged_changes()
    touches_code = any(change.path.startswith(code_prefixes) for change in staged_changes)
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
        if number in delivered_numbers and _plan_status(context, plan_doc_re, number) is (
            PlanStatus.NOT_STARTED
        ):
            findings.append(
                Finding(
                    check_id=CHECK_ID,
                    level=Level.BLOCK,
                    message=(
                        f"Commit ships code for Plan {number:05d} but its PLAN.md "
                        "still reads `Not Started`"
                    ),
                    remediation=(
                        "Set `**Status**: In Progress` in that plan's PLAN.md and stage it "
                        "in this same commit — shipping code for a plan is what starting it "
                        "means."
                    ),
                )
            )
            continue
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
