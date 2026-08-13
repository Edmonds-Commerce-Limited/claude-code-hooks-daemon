"""Check ``journal-dayfile-naming`` (Stage 1, advise; Plan 00163).

A journal day-file written under a plan's ``JOURNAL/`` directory must be named
``NNNNN-Journal-YY-MM-DD.md`` where ``NNNNN`` is the enclosing plan number and
``YY-MM-DD`` is a real calendar date.

Scope is deliberately grammar-only (SRP, Plan 00197): the embedded number must
match the enclosing plan and the date must be a real calendar date, but WHICH
date is fresh enough to write is ``journal-dayfile-is-today``'s job — that
split keeps the two checks from ever giving contradictory advice about one
file (this check used to tolerate a yesterday-dated name as a "legitimate
midnight rollover"; that tolerance is exactly the confusion the newer check
was written to close, so it moved rather than staying duplicated here).

Ships ADVISE (Decision 4); honours ``plan_workflow.qa.journal.mode: block``.

Registered at EDIT *and* SWEEP (Plan 00230). The rule is a pure function of a
FILENAME, so a day-file whose name predates the grammar is an on-disk fact a
write-time-only registration can never revisit.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    JournalEditTarget,
    journal_edit_target,
    journal_level,
    journal_tree_targets,
)
from claude_code_hooks_daemon.plan_qa.model import parse_journal_dayfile_name
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "journal-dayfile-naming"

_REMEDIATION: Final[str] = (
    "Name journal day-files `NNNNN-Journal-YY-MM-DD.md` where NNNNN is the "
    "enclosing plan number and YY-MM-DD is today's date, e.g. "
    "`00163-Journal-26-07-14.md`. Let `mkplan.bash` scaffold the first one."
)


def _rule(context: CheckContext, target: JournalEditTarget) -> list[Finding]:
    level = journal_level(context)
    parsed = parse_journal_dayfile_name(target.basename)
    if parsed is None:
        return [
            Finding(
                check_id=CHECK_ID,
                level=level,
                message=(
                    f"Journal day-file `{target.basename}` does not match the "
                    "`NNNNN-Journal-YY-MM-DD.md` grammar"
                ),
                remediation=_REMEDIATION,
                path=target.rel_path,
            )
        ]

    problems: list[str] = []
    if target.plan_number is not None and parsed.number != target.plan_number:
        problems.append(
            f"embedded number {parsed.number:05d} does not match the enclosing "
            f"plan {target.plan_number:05d}"
        )
    if not parsed.is_valid_date:
        problems.append(
            f"{parsed.year:04d}-{parsed.month:02d}-{parsed.day:02d} is not a real calendar date"
        )

    if not problems:
        return []
    return [
        Finding(
            check_id=CHECK_ID,
            level=level,
            message="Journal day-file name issues: " + "; ".join(problems),
            remediation=_REMEDIATION,
            path=target.rel_path,
        )
    ]


def _run_edit(context: CheckContext) -> list[Finding]:
    target = journal_edit_target(context)
    return [] if target is None else _rule(context, target)


def _run_sweep(context: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    for target in journal_tree_targets(context):
        findings.extend(_rule(context, target))
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=Stage.EDIT, level=Level.ADVISE, sins=(), run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=Stage.SWEEP, level=Level.ADVISE, sins=(), run=_run_sweep),
)
