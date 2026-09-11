"""Check ``journal-entry-ordering`` (Stage 1 + 3, advise; Plan 00377 N1).

A journal day-file's own preamble states the grammar "times increase down the
file". Nothing enforced it, and a file that breaks it quietly voids the
journal's central contract: the next agent's entry point is the LAST entry of
the newest day-file, which is only useful while the last entry is the latest.

Measured gap this closes: a day-file whose entries ran
12:49 -> 12:58 -> 13:00 -> 12:50 passed ``plan-qa --sweep`` with 0 findings.
``journal-append-only`` did fire on the EDIT that displaced the entry, so the
hole was specifically the sweep — hence the dual EDIT + SWEEP registration
(Plan 00230's reasoning): entry order is a fact about a file ON DISK, and a
write-time-only check can never revisit a file written before the rule existed.

Equal times PASS. Two entries in the same minute is ordinary — only a time
EARLIER than one above it is a defect.
"""

import re
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    JournalEditTarget,
    journal_edit_target,
    journal_level,
    journalling_active,
)
from claude_code_hooks_daemon.plan_qa.model import PlanLocation, parse_journal_dayfile_name
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "journal-entry-ordering"

#: No backfill, mirroring Plan 00163 Decision 7's grandfathering: the SWEEP
#: half ignores day-files NAMED before the date this rule shipped. A file
#: written before the rule existed could not have complied with it, and the
#: only "fix" available for one is rewriting a historical record that is
#: append-only by contract — for the journals on disk here that would mean
#: inventing timestamps, because their true order is the narrative order and
#: it is the CLOCK READINGS that are wrong. A permanently unfixable finding
#: trains readers to ignore the check.
#:
#: The sweep still earns its registration after this cutoff: it is the only
#: half that sees a day-file written by something the EDIT hook never
#: observed — a Bash heredoc, a merge, an external tool.
#: Four-digit year: ``parse_journal_dayfile_name`` expands the day-file name's
#: ``YY`` to a full year, so a two-digit tuple here would never compare true.
_NO_BACKFILL_BEFORE: Final[tuple[int, int, int]] = (2026, 9, 11)

#: An entry heading at the START of a line: ``## HH:MM · category · REF``.
#: Anchored with no leading whitespace on purpose — the preamble quotes the
#: grammar inside a blockquote (``> ## HH:MM …``), which must never count.
_ENTRY_HEADING: Final[re.Pattern[str]] = re.compile(r"^## (\d{2}):(\d{2})\b")

#: Journals embed fenced logs and diffs without limit, and those bodies can
#: contain entry-shaped lines quoted from elsewhere. Tracking the fence state
#: is what stops a quoted heading being read as this file's own entry.
_FENCE: Final[re.Pattern[str]] = re.compile(r"^\s*(```|~~~)")

_REMEDIATION: Final[str] = (
    "Journal entries run oldest-first: move the out-of-order entry back to its "
    "chronological slot, keeping its text unchanged. If it records something "
    "that happened later than its timestamp suggests, correct it with a NEW "
    "entry at the bottom rather than restating the old one — journals are "
    "append-only, so a correction is an addition."
)


def _entry_times(content: str) -> list[tuple[int, str]]:
    """Every entry heading's time, in file order, as (minutes, ``HH:MM``)."""
    times: list[tuple[int, str]] = []
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
        hours, minutes = int(match.group(1)), int(match.group(2))
        times.append((hours * 60 + minutes, f"{match.group(1)}:{match.group(2)}"))
    return times


def _rule(context: CheckContext, target: JournalEditTarget, content: str) -> list[Finding]:
    times = _entry_times(content)
    regressions: list[str] = []
    highest, highest_label = -1, ""
    for minutes, label in times:
        if minutes < highest:
            regressions.append(f"`{label}` appears after `{highest_label}`")
        else:
            highest, highest_label = minutes, label

    if not regressions:
        return []
    return [
        Finding(
            check_id=CHECK_ID,
            level=journal_level(context),
            message=(
                f"Journal entries in `{target.basename}` are out of chronological "
                "order (the day-file grammar is that times increase down the "
                "file): " + "; ".join(regressions)
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


def _live_journal_targets(context: CheckContext) -> list[JournalEditTarget]:
    """Journal day-files belonging to plans still in the plan ROOT.

    Deliberately NOT the shared ``journal_tree_targets``, which also walks
    ``Completed/`` and ``Cancelled/``. Archived journals are excluded for a
    reason that is not merely noise-reduction: ``archive-immutability`` forbids
    editing them, so an ordering finding there is one nobody is PERMITTED to
    act on, and a permanently unfixable finding trains readers to ignore the
    check. The value of this rule is also live-only — it protects the contract
    that the next agent's entry point is the last entry of the newest day-file,
    and an archived plan has no next agent.

    Measured when the check first ran over this repository: every violation on
    disk sat in ``Completed/``.
    """
    if context.tree is None or not journalling_active(context):
        return []

    targets: list[JournalEditTarget] = []
    for folder in context.tree.folders:
        if folder.location != PlanLocation.ROOT:
            continue
        journal_dir = folder.path / context.journal_dir_name
        if not journal_dir.is_dir():
            continue
        for entry in sorted(journal_dir.iterdir()):
            if not entry.is_file() or entry.suffix != ".md":
                continue
            parsed = parse_journal_dayfile_name(entry.name)
            if parsed is None or (parsed.year, parsed.month, parsed.day) < _NO_BACKFILL_BEFORE:
                # Unparseable names are journal-dayfile-naming's finding, not
                # this one; pre-cutoff names are grandfathered.
                continue
            targets.append(
                JournalEditTarget(
                    rel_path=str(entry.relative_to(context.project_root)),
                    plan_number=folder.number,
                    basename=entry.name,
                )
            )
    return targets


def _run_sweep(context: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    for target in _live_journal_targets(context):
        path = context.project_root / target.rel_path
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # A day-file that cannot be read is not an ordering defect, and
            # reporting it as one would be wrong. Say what happened instead of
            # discarding it, so an unreadable journal is still visible.
            findings.append(
                Finding(
                    check_id=CHECK_ID,
                    level=Level.ADVISE,
                    message=f"Journal day-file `{target.basename}` could not be read: {exc}",
                    remediation="Fix the file's permissions or encoding, then re-run the sweep.",
                    path=target.rel_path,
                )
            )
            continue
        findings.extend(_rule(context, target, content))
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=Stage.EDIT, level=Level.ADVISE, sins=(), run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=Stage.SWEEP, level=Level.ADVISE, sins=(), run=_run_sweep),
)
