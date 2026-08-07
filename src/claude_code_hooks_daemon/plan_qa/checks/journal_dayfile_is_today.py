"""Check ``journal-dayfile-is-today`` (Stage 1, block by default; Plan 00197).

A journal day-file edit whose embedded date is not EXACTLY today is blocked.
Unlike ``journal-dayfile-naming`` (which tolerates yesterday as a legitimate
midnight-rollover exception), this check treats the rollover as the MAIN case
it defends against: an agent whose session spans midnight must start today's
day-file, not keep appending to yesterday's — that confusion is precisely
what "never log against the wrong day" means.

Scope is deliberately narrow (SRP): grammar, plan-number coherence and
calendar validity all remain ``journal-dayfile-naming``'s job. This check only
judges recency of an otherwise well-formed, parseable name — a malformed name
or an impossible calendar date defers entirely (returns no finding) so the two
checks never produce contradictory advice about the same file.

Ships BLOCK by default via its own ``today_only_mode`` knob, independent of
``journal_mode`` — the write-time freshness rule is not given the advise-first
rollout grace period the original journalling checks received (Decision 4 in
``journal_dayfile_naming``), because the user-reported failure mode is agents
silently mis-filing entries, not a rollout concern.
"""

from datetime import date
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    journal_edit_target,
    journal_today_only_level,
    level_for_plan,
)
from claude_code_hooks_daemon.plan_qa.model import parse_journal_dayfile_name
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "journal-dayfile-is-today"

_GENERIC_REMEDIATION: Final[str] = (
    "Journals are append-only per-day logs — never edit a stale day-file, even "
    "one dated yesterday. Write to today's day-file instead, named "
    "`NNNNN-Journal-YY-MM-DD.md` with today's date (create it if it does not "
    "exist yet)."
)


def _suggested_filename(plan_number: int, today: date) -> str:
    """The exact today-dated day-file name an agent should write to instead."""
    return f"{plan_number:05d}-Journal-{today.strftime('%y-%m-%d')}.md"


def _remediation(plan_number: int | None, today: date) -> str:
    if plan_number is None:
        return _GENERIC_REMEDIATION
    suggested = _suggested_filename(plan_number, today)
    return (
        "Journals are append-only per-day logs — never edit a stale day-file, "
        f"even one dated yesterday. Write to today's day-file instead: "
        f"`{suggested}` (create it if it does not exist yet)."
    )


def _run(context: CheckContext) -> list[Finding]:
    target = journal_edit_target(context)
    if target is None:
        return []

    level = journal_today_only_level(context)
    if level is None:
        return []

    # Grammar / plan-number / calendar-validity problems belong to
    # journal-dayfile-naming; deferring here (rather than re-reporting) keeps
    # the two checks from ever giving contradictory advice about one file.
    parsed = parse_journal_dayfile_name(target.basename)
    if parsed is None or not parsed.is_valid_date:
        return []

    # Fail OPEN on an unknown clock (e.g. the `plan-qa --lint` CLI path never
    # supplies `today`) — blocking on missing date information would be worse
    # than the bug this check exists to catch.
    if context.today is None:
        return []

    if parsed.date == context.today:
        return []

    if level is Level.BLOCK:
        level = level_for_plan(context, target.plan_number)

    return [
        Finding(
            check_id=CHECK_ID,
            level=level,
            message=(
                f"Journal day-file `{target.basename}` is dated "
                f"{parsed.date.isoformat()}, not today ({context.today.isoformat()})"
            ),
            remediation=_remediation(target.plan_number, context.today),
            path=target.rel_path,
        )
    ]


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.EDIT,
    level=Level.BLOCK,
    sins=(),
    run=_run,
)
