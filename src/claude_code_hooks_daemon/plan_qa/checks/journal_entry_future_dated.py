"""Check ``journal-entry-future-dated`` (Stage 1, advise; Plan 00377 N9).

A journal entry timestamped ahead of the clock cannot be right, and nothing
noticed when it happened. Measured: entries in a live day-file ran ~70 minutes
ahead of real time, because the timestamps were estimated rather than read, and
the drift was caught only by chance when a later entry had to be placed.

Neither existing journal check can see this. ``journal-entry-ordering`` asks
whether times increase down the file, and a uniformly wrong run does;
``journal-append-only`` asks whether earlier entries were rewritten, and nothing
was. A sequence that is internally consistent and collectively wrong satisfies
both — so the only external reference left is the clock.

**Only the FUTURE direction is judged.** Writing up something that happened
earlier is ordinary journalling and stays silent. A time that has not arrived
yet is the one reading that cannot be explained by anything but a mistake.

**EDIT stage only — deliberately not dual-registered**, which is where this
departs from ``journal-entry-ordering``'s reasoning (Plan 00230). That check
sweeps because an out-of-order entry can, in principle, be moved. A wrong
timestamp cannot be corrected at all without rewriting a record that is
append-only by contract, so a sweep could only ever emit findings nobody is
permitted to act on — the exact "permanently unfixable finding trains readers
to ignore the check" failure its sibling was careful to avoid. At EDIT time the
entry has not landed, and fixing it costs one keystroke.
"""

from datetime import UTC, datetime
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    JournalEditTarget,
    journal_edit_target,
    journal_level,
)
from claude_code_hooks_daemon.plan_qa.model import (
    journal_entry_headings,
    parse_journal_dayfile_name,
)
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "journal-entry-future-dated"

#: How far ahead of the clock an entry may sit before it is reported. Generous
#: on purpose: a write takes time, clocks skew, and an agent that rounds up to
#: the next quarter hour is being approximate rather than wrong. The defect
#: this exists for was over an hour out, so a tight bound buys nothing but
#: false positives.
_TOLERANCE_MINUTES: Final[int] = 30

#: The substring of `_JOURNAL_TEMPLATE_.md`'s preamble sentinel that states the
#: file's zone (Plan 00427). Matched as a substring rather than a whole line so
#: surrounding emphasis or punctuation in the template cannot silently unmatch
#: it; `tests/unit/scripts/test_journal_sentinel_sync.py` pins it against every
#: shipped copy, because a sentinel that stops matching fails SILENTLY — the
#: check just goes back to the local clock.
_UTC_SENTINEL: Final[str] = "timestamps in this file are UTC"

_REMEDIATION: Final[str] = (
    "Read the clock rather than estimating it, and correct the timestamp before "
    "this write lands — once the entry is committed the journal is append-only, "
    "so the reading can never be fixed, only annotated by a later entry. If the "
    "entry genuinely belongs to a different day, write it to that day's file."
)


def _now() -> datetime:
    """Current local time, isolated so tests can pin it."""
    return datetime.now()


def _utc_now() -> datetime:
    """Current UTC time as a naive value, isolated so tests can pin it.

    Naive on purpose: an entry's time is rebuilt naive from the day-file name,
    and comparing an aware value against it raises rather than reports.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _is_utc_dayfile(content: str) -> bool:
    """Whether this day-file says the scaffolder wrote it, in UTC.

    The sentinel is the only record of which clock a day-file's times were read
    by, so it is also the only sound basis for choosing the clock to judge them
    against. Its ABSENCE means legacy — local times, zone unrecorded — which is
    why the old behaviour is the fallback rather than the other way round.
    """
    return _UTC_SENTINEL in content


def _rule(context: CheckContext, target: JournalEditTarget, content: str) -> list[Finding]:
    parsed = parse_journal_dayfile_name(target.basename)
    if parsed is None:
        # An unparseable name is journal-dayfile-naming's finding, and without
        # a date there is nothing to compare a time against.
        return []

    headings = journal_entry_headings(content)
    if not headings:
        return []

    latest = max(headings, key=lambda heading: heading.minutes)
    label = latest.label
    try:
        entry_at = datetime(parsed.year, parsed.month, parsed.day, latest.hour, latest.minute)
    except ValueError:
        # An impossible clock reading (25:61) is a grammar defect, not a
        # drift one; reporting it here would put it under the wrong check.
        return []

    now = _utc_now() if _is_utc_dayfile(content) else _now()
    ahead_minutes = (entry_at - now).total_seconds() / 60
    if ahead_minutes <= _TOLERANCE_MINUTES:
        return []

    return [
        Finding(
            check_id=CHECK_ID,
            level=journal_level(context),
            message=(
                f"Journal entry `{label}` in `{target.basename}` is "
                f"{int(ahead_minutes)} minutes ahead of the clock "
                f"({now:%H:%M}). A timestamp that has not arrived yet is wrong, "
                "and once committed it cannot be corrected — the journal is "
                "append-only."
            ),
            remediation=_REMEDIATION,
            path=target.rel_path,
        )
    ]


def _run_edit(context: CheckContext) -> list[Finding]:
    target = journal_edit_target(context)
    if target is None or context.file_content is None:
        return []
    return _rule(context, target, context.file_content)


CHECKS: Final[tuple[CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=Stage.EDIT, level=Level.ADVISE, sins=(), run=_run_edit),
)
