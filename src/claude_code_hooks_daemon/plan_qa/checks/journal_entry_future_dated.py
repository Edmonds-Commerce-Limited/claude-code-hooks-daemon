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

import re
from datetime import datetime
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    JournalEditTarget,
    journal_edit_target,
    journal_level,
)
from claude_code_hooks_daemon.plan_qa.model import parse_journal_dayfile_name
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Level, Stage

CHECK_ID: Final[str] = "journal-entry-future-dated"

#: How far ahead of the clock an entry may sit before it is reported. Generous
#: on purpose: a write takes time, clocks skew, and an agent that rounds up to
#: the next quarter hour is being approximate rather than wrong. The defect
#: this exists for was over an hour out, so a tight bound buys nothing but
#: false positives.
_TOLERANCE_MINUTES: Final[int] = 30

#: An entry heading at the START of a line. Anchored with no leading whitespace
#: because the preamble quotes the grammar inside a blockquote, which is
#: documentation rather than an entry.
_ENTRY_HEADING: Final[re.Pattern[str]] = re.compile(r"^## (\d{2}):(\d{2})\b")

#: Fenced bodies may quote entry-shaped lines from elsewhere; tracking the
#: fence state stops a quoted heading being read as this file's own entry.
_FENCE: Final[re.Pattern[str]] = re.compile(r"^\s*(```|~~~)")

_REMEDIATION: Final[str] = (
    "Read the clock rather than estimating it, and correct the timestamp before "
    "this write lands — once the entry is committed the journal is append-only, "
    "so the reading can never be fixed, only annotated by a later entry. If the "
    "entry genuinely belongs to a different day, write it to that day's file."
)


def _now() -> datetime:
    """Current local time, isolated so tests can pin it."""
    return datetime.now()


def _latest_entry(content: str) -> tuple[int, int, str] | None:
    """The highest ``(hour, minute, label)`` among real entry headings."""
    latest: tuple[int, int, str] | None = None
    in_fence = False
    for line in content.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _ENTRY_HEADING.match(line)
        if match is None:
            continue
        hour, minute = int(match.group(1)), int(match.group(2))
        label = f"{match.group(1)}:{match.group(2)}"
        if latest is None or (hour, minute) > (latest[0], latest[1]):
            latest = (hour, minute, label)
    return latest


def _rule(context: CheckContext, target: JournalEditTarget, content: str) -> list[Finding]:
    parsed = parse_journal_dayfile_name(target.basename)
    if parsed is None:
        # An unparseable name is journal-dayfile-naming's finding, and without
        # a date there is nothing to compare a time against.
        return []

    latest = _latest_entry(content)
    if latest is None:
        return []

    hour, minute, label = latest
    try:
        entry_at = datetime(parsed.year, parsed.month, parsed.day, hour, minute)
    except ValueError:
        # An impossible clock reading (25:61) is a grammar defect, not a
        # drift one; reporting it here would put it under the wrong check.
        return []

    now = _now()
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
