"""Check ``journal-dayfile-naming`` (Stage 1, advise; Plan 00163).

A journal day-file written under a plan's ``JOURNAL/`` directory must be named
``NNNNN-Journal-YY-MM-DD.md`` where ``NNNNN`` is the enclosing plan number and
``YY-MM-DD`` is a real calendar date — today or yesterday when the surface
knows the date (local midnight rollover mid-session is legitimate, observed in
this feature's own originating session).

Ships ADVISE (Decision 4); this is the ONLY journal check that may ever ratchet
to BLOCK via ``plan_workflow.qa.journal.mode: block``.
"""

from datetime import timedelta
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import journal_edit_target, journal_level
from claude_code_hooks_daemon.plan_qa.model import parse_journal_dayfile_name
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "journal-dayfile-naming"

_ONE_DAY: Final[timedelta] = timedelta(days=1)

_REMEDIATION: Final[str] = (
    "Name journal day-files `NNNNN-Journal-YY-MM-DD.md` where NNNNN is the "
    "enclosing plan number and YY-MM-DD is today's (or yesterday's) date, e.g. "
    "`00163-Journal-26-07-14.md`. Let `mkplan.bash` scaffold the first one."
)


def _run(context: CheckContext) -> list[Finding]:
    target = journal_edit_target(context)
    if target is None:
        return []

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
    elif context.today is not None and parsed.date not in (context.today, context.today - _ONE_DAY):
        problems.append(
            f"date {parsed.date.isoformat()} is neither today nor yesterday "
            f"({context.today.isoformat()})"
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


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.EDIT,
    level=Level.ADVISE,
    sins=(),
    run=_run,
)
