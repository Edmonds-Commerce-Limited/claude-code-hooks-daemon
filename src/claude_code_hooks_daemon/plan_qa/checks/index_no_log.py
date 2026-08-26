"""Check ``index-no-log`` (Stage 1/2/3, advise).

The plan index states CURRENT TRUTH only — it is a pointer table, not a
changelog. History belongs in git and in each plan's ``JOURNAL/``, never in
the index itself (Core Standard: `[[plan_workflow]]` in ``CLAUDE.md``).

Twice the index re-grew a stacked reconciliation LEDGER: successive
recount entries written in LOG grammar — "- **Before that**: 38 root, ...",
recording what the count used to be rather than what it is now. This is
changelog creep inside a file that is supposed to be immune to it. The byte
ceiling on other plan documents does not even apply to the index (it is
correctly exempt — it is not a plan), so nothing else was catching this
shape before it accumulated again.

This check catches the SHAPE, not the size: a bullet written in
retrospective log grammar ("Before that", "Prior to that", "Previously", or a
bold ISO date) is flagged regardless of how short the file currently is —
unlike ``index-row-length``'s worsening/tiering machinery, there is no
grow/shrink axis to tier on here, so every surface is a fixed ADVISE.

Mirrors ``index_row_length`` in structure: same three surfaces (EDIT, COMMIT,
SWEEP), same :data:`PlanFileKind.PLAN_INDEX` scoping via :func:`classify`.
"""

import re
from typing import Final

from claude_code_hooks_daemon.plan_qa.model import README_FILENAME
from claude_code_hooks_daemon.plan_qa.paths import PlanFileKind, classify
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "index-no-log"

# How many offending phrases to name before summarising the rest, so a badly
# degraded index produces a usable message instead of a wall of text.
_MAX_LISTED_OFFENDERS: Final[int] = 5

# Ledger grammar: a bold lead-in naming a PAST recount, or a bold ISO date —
# both are journal grammar, not index grammar. Anchored to a bullet's bold
# lead-in so "the index carries no reconciliation history" prose (which
# quotes these very phrases to disclaim them) is not itself matched.
_LEDGER_LEAD_INS: Final[tuple[str, ...]] = ("Before that", "Prior to that", "Previously")
_LEDGER_PHRASE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^-\s+\*\*(" + "|".join(re.escape(phrase) for phrase in _LEDGER_LEAD_INS) + r")\*\*\s*:",
)
_LEDGER_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^-\s+\*\*(\d{4}-\d{2}-\d{2})\*\*\s*:",
)

_REMEDIATION: Final[str] = (
    "State current truth only — delete the historical recount line. Earlier "
    "recounts already live in git history; if the narrative itself is worth "
    "keeping, relocate it to a plan's JOURNAL/ rather than the index."
)


def _matched_phrase(line: str) -> str | None:
    lead_in_match = _LEDGER_PHRASE_PATTERN.match(line)
    if lead_in_match is not None:
        return lead_in_match.group(1)
    date_match = _LEDGER_DATE_PATTERN.match(line)
    if date_match is not None:
        return date_match.group(1)
    return None


def _ledger_lines(lines: tuple[str, ...]) -> tuple[tuple[int, str], ...]:
    """``(line_number, matched_phrase)`` for every ledger-grammar line, 1-based."""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(lines, 1):
        phrase = _matched_phrase(line.strip())
        if phrase is not None:
            found.append((number, phrase))
    return tuple(found)


def _message(offenders: tuple[tuple[int, str], ...]) -> str:
    listed = offenders[:_MAX_LISTED_OFFENDERS]
    detail = ", ".join(f"line {number} ('{phrase}')" for number, phrase in listed)
    remainder = len(offenders) - len(listed)
    if remainder > 0:
        detail += f", and {remainder:,} more"
    singular = len(offenders) == 1
    subject = "line" if singular else "lines"
    verb = "reads" if singular else "read"
    return (
        f"{len(offenders):,} {subject} in the plan index {verb} as a "
        f"historical ledger entry rather than current truth: {detail}."
    )


def _finding(offenders: tuple[tuple[int, str], ...], rel_path: str) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        level=Level.ADVISE,
        message=_message(offenders),
        remediation=_REMEDIATION,
        path=rel_path,
    )


def _run_edit(context: CheckContext) -> list[Finding]:
    """Stage 1: the would-be content of a Write/Edit to the plan index."""
    if context.file_path is None or context.file_content is None:
        return []
    classified = classify(context.file_path, context)
    if classified.kind is not PlanFileKind.PLAN_INDEX:
        return []

    offenders = _ledger_lines(tuple(context.file_content.split("\n")))
    if not offenders:
        return []
    return [_finding(offenders, classified.rel_path)]


def _run_tree(context: CheckContext) -> list[Finding]:
    """Stages 2 and 3: the index as it stands, from the parsed tree view."""
    readme: ReadmeIndex | None = context.readme
    if readme is None:
        return []
    offenders = _ledger_lines(readme.lines)
    if not offenders:
        return []
    rel_path = f"{context.plan_dir_rel.rstrip('/')}/{README_FILENAME}"
    return [_finding(offenders, rel_path)]


CHECKS: Final[tuple[CheckSpec, CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=Stage.EDIT, level=Level.ADVISE, sins=(), run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=Stage.COMMIT, level=Level.ADVISE, sins=(), run=_run_tree),
    CheckSpec(check_id=CHECK_ID, stage=Stage.SWEEP, level=Level.ADVISE, sins=(), run=_run_tree),
)
