"""Check ``index-row-length`` (Stage 1/2/3, block; Plan 00218).

The plan index is the entry point to every plan in the tree, and the one
property that makes an index usable is that each row can be read at a glance.
**A row is a pointer, not a summary**: a link, a status and one clause. The
rationale belongs in the linked ``PLAN.md`` — keeping a copy in the index means
maintaining the same paragraph twice, and the copy is the one that goes stale.

This is the FAST equivalent of
``tests/integration/test_plan_index_navigability.py``, which is the batch
equivalent and stays exactly as it is (``CLAUDE.md`` Core Standard 15: a
write-time guard never sees what is already on disk, so both are needed). The
suite guard's only feedback path is a full pytest run, so an over-long row was
invisible until long after the commit that introduced it.

Two design points that keep the two guards honest with each other:

- **One definition of the limit.** Both read
  :data:`DEFAULT_INDEX_ROW_MAX_CHARS`. A second literal is how they would drift.
- **One definition of a violation.** Both measure EVERY line, not only parsed
  index rows. A 900-character prose paragraph or statistics bullet is the same
  navigability failure as a 900-character row, and a narrower fast rule would
  pass content the suite then fails on.

At EDIT the check tiers exactly as ``plan-doc-size`` does: only an edit that
makes the file WORSE can block. An index that somehow acquired a long row must
stay editable — including by the edit that fixes it.

This is deliberately a SEPARATE check rather than a special case bolted onto
the per-plan size tiers. The index is correctly exempt from those (it is not a
plan), and that rule stays crisp.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.model import README_FILENAME
from claude_code_hooks_daemon.plan_qa.paths import PlanFileKind, classify
from claude_code_hooks_daemon.plan_qa.types import (
    DEFAULT_INDEX_ROW_MAX_CHARS,
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "index-row-length"

# How many offending lines to name before summarising the rest, so a badly
# degraded index produces a usable message instead of a wall of text.
_MAX_LISTED_OFFENDERS: Final[int] = 5

_REMEDIATION: Final[str] = (
    "Reduce each line to a link, a status and ONE clause, and move the "
    "rationale into that plan's own PLAN.md — that is what the link is for, "
    "and a second copy in the index is the one that goes stale."
)


def _over_limit(lines: tuple[str, ...]) -> tuple[tuple[int, int], ...]:
    """``(line_number, length)`` for every line past the limit, 1-based.

    ``>`` not ``>=``: the limit itself is allowed, matching the batch guard.
    """
    return tuple(
        (number, len(line))
        for number, line in enumerate(lines, 1)
        if len(line) > DEFAULT_INDEX_ROW_MAX_CHARS
    )


def _message(offenders: tuple[tuple[int, int], ...]) -> str:
    listed = offenders[:_MAX_LISTED_OFFENDERS]
    detail = ", ".join(f"line {number} ({length:,} chars)" for number, length in listed)
    remainder = len(offenders) - len(listed)
    if remainder > 0:
        detail += f", and {remainder:,} more"
    singular = len(offenders) == 1
    subject = "line" if singular else "lines"
    verb = "exceeds" if singular else "exceed"
    return (
        f"{len(offenders):,} {subject} in the plan index {verb} "
        f"{DEFAULT_INDEX_ROW_MAX_CHARS:,} characters: {detail}. A row a reader "
        f"must scroll horizontally to finish is not an index row."
    )


def _finding(offenders: tuple[tuple[int, int], ...], level: Level, rel_path: str) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        level=level,
        message=_message(offenders),
        remediation=_REMEDIATION,
        path=rel_path,
    )


def _worsens(
    before: tuple[tuple[int, int], ...],
    after: tuple[tuple[int, int], ...],
) -> bool:
    """Whether the edit made the index harder to scan than it already was.

    Two independent ways to worsen it, mirroring ``plan-doc-size``'s grow /
    shrink / same-size tiering on the axis that matters here: MORE over-limit
    lines than before, or a longer worst offender. Anything else — fixing one,
    shortening one, or touching an unrelated part of the file — never blocks,
    so an already-degraded index is never trapped.
    """
    if len(after) > len(before):
        return True
    return max((length for _, length in after), default=0) > max(
        (length for _, length in before), default=0
    )


def _run_edit(context: CheckContext) -> list[Finding]:
    """Stage 1: the would-be content of a Write/Edit to the plan index."""
    if context.file_path is None or context.file_content is None:
        return []
    classified = classify(context.file_path, context)
    if classified.kind is not PlanFileKind.PLAN_INDEX:
        return []

    offenders = _over_limit(tuple(context.file_content.split("\n")))
    if not offenders:
        return []

    before_content = context.file_content_before
    before = _over_limit(tuple(before_content.split("\n"))) if before_content is not None else ()
    level = Level.BLOCK if _worsens(before, offenders) else Level.ADVISE
    return [_finding(offenders, level, classified.rel_path)]


def _run_tree(context: CheckContext) -> list[Finding]:
    """Stages 2 and 3: the index as it stands, from the parsed tree view."""
    readme = context.readme
    if readme is None:
        return []
    offenders = _over_limit(readme.lines)
    if not offenders:
        return []
    rel_path = f"{context.plan_dir_rel.rstrip('/')}/{README_FILENAME}"
    return [_finding(offenders, Level.BLOCK, rel_path)]


CHECKS: Final[tuple[CheckSpec, CheckSpec, CheckSpec]] = (
    # No 00144 audit-catalogue sin: the index-as-paragraphs failure mode was
    # identified by Plan 00218, well after that catalogue was written.
    CheckSpec(check_id=CHECK_ID, stage=Stage.EDIT, level=Level.BLOCK, sins=(), run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=Stage.COMMIT, level=Level.BLOCK, sins=(), run=_run_tree),
    CheckSpec(check_id=CHECK_ID, stage=Stage.SWEEP, level=Level.BLOCK, sins=(), run=_run_tree),
)
