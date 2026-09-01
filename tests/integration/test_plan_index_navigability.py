"""The plan index must stay navigable.

DBF (``CLAUDE.md`` Core Standard 15). The daemon enforces size tiers on every
``PLAN.md`` (advisory 18,000 bytes / 350 lines, blocked at 35,000 / 900) for one
reason: a document re-read in full every session charges its size to every
session. ``CLAUDE/Plan/README.md`` is exactly such a document — it is the entry
point to 199 plans — and it is EXEMPT from those tiers, because the tiers are a
per-plan rule and the index is not a plan.

Nothing else bounded it, so it grew to 144,626 bytes with a 2,830-character
line: the one document meant to make the plan tree navigable had become the
least navigable file in the repository. That is the exemption working exactly
as designed and no guard noticing the consequence.

This is the batch guard. It bounds the two properties that actually make an
index usable — total size and per-row scannability — and nothing else.

The per-row ceiling now ALSO has a fast-loop guard: the plan_qa
``index-row-length`` check (Plan 00218), which reads
:data:`DEFAULT_INDEX_ROW_MAX_CHARS` — the same constant imported below — so the
two can never disagree about the limit or about what counts as a violation.
That is a SEPARATE check, not a special case bolted onto the per-plan size
tiers: the index stays correctly exempt from those, and the rule that is
currently crisp stays crisp. This file remains the batch equivalent, because a
write-time guard never sees what is already on disk (``CLAUDE.md`` Core
Standard 15) — a long row can arrive by merge, by script, or from a worktree.

**A row is a pointer, not a summary.** The full rationale belongs in the linked
``PLAN.md``; keeping a copy in the index means maintaining the same paragraph in
two places, and the copy is the one that goes stale.
"""

from __future__ import annotations

import re
from pathlib import Path

from claude_code_hooks_daemon.plan_qa.types import DEFAULT_INDEX_ROW_MAX_CHARS

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX = REPO_ROOT / "CLAUDE" / "Plan" / "README.md"
COMPLETED_ARCHIVE = REPO_ROOT / "CLAUDE" / "Plan" / "Completed" / "README.md"

# Ceilings, not targets. Chosen with ~200 plans indexed and roughly 40% of
# headroom left, so ordinary growth never trips them and a return to
# paragraph-per-row does.
MAX_BYTES = 130_000

# Plan 00310: Completed rows age out of the main index. The 30 highest-numbered
# completed plans stay here; everything older lives verbatim in
# CLAUDE/Plan/Completed/README.md. This is the cause-side guard (row count),
# complementing the symptom-side byte ceiling above.
MAX_COMPLETED_ROWS = 30

_COMPLETED_ROW_RE = re.compile(r"^- \[\d+")

# IMPORTED, never redeclared (Plan 00218). The per-line ceiling is now also
# enforced in the fast loop by the plan_qa ``index-row-length`` check, and two
# guards over one rule must read one number — a local literal here is exactly
# how the fast and batch guards would drift apart. The total-size ceiling above
# has no fast-loop equivalent, so it stays local.
MAX_LINE_CHARS = DEFAULT_INDEX_ROW_MAX_CHARS


def _lines() -> list[str]:
    return INDEX.read_text(encoding="utf-8").split("\n")


def test_index_exists() -> None:
    """Guards the two tests below from passing vacuously on a missing file."""
    assert INDEX.is_file(), f"plan index missing at {INDEX}"


def test_index_stays_under_the_size_ceiling() -> None:
    size = INDEX.stat().st_size
    assert size <= MAX_BYTES, (
        f"CLAUDE/Plan/README.md is {size:,} bytes (ceiling {MAX_BYTES:,}).\n"
        "Compact the rows: each should be a link, a status and ONE clause. The "
        "full rationale belongs in the linked PLAN.md — that is what the link "
        "is for, and a second copy here is the one that goes stale."
    )


def test_completed_rows_stay_within_the_retention_window() -> None:
    """Completed rows age out; only the newest MAX_COMPLETED_ROWS may remain.

    A main-README row count above the window means an archival forgot the
    age-out step from the Plan Completion Checklist: add the new row, then
    move rows beyond the window to CLAUDE/Plan/Completed/README.md, verbatim,
    in the same commit.
    """
    lines = _lines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## Completed Plans")
    except StopIteration:
        return  # test_index_exists / structural change would already fail elsewhere
    end = next(
        (i for i, line in enumerate(lines) if i > start and line.startswith("## ")),
        len(lines),
    )
    row_count = sum(1 for line in lines[start:end] if _COMPLETED_ROW_RE.match(line))

    assert row_count <= MAX_COMPLETED_ROWS, (
        f"CLAUDE/Plan/README.md has {row_count} completed rows "
        f"(retention window: {MAX_COMPLETED_ROWS}).\n"
        "Age out the oldest rows: move every completed row beyond the "
        f"{MAX_COMPLETED_ROWS} highest-numbered plans, verbatim, into "
        f"{COMPLETED_ARCHIVE.relative_to(REPO_ROOT)}, per the Plan Completion "
        "Checklist in CLAUDE/PlanWorkflow.md."
    )


def test_no_index_row_is_a_paragraph() -> None:
    """A row a reader must scroll horizontally to finish is not an index row."""
    offenders = [
        (number, len(line)) for number, line in enumerate(_lines(), 1) if len(line) > MAX_LINE_CHARS
    ]

    assert not offenders, (
        f"{len(offenders)} line(s) exceed {MAX_LINE_CHARS} characters:\n"
        + "\n".join(f"  line {number}: {length:,} chars" for number, length in offenders)
        + "\nReduce each to a link, a status and one clause; move the rationale "
        "into that plan's own PLAN.md."
    )
