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

This is the missing guard. It is deliberately NOT a plan-QA check: the index is
correctly exempt from the per-plan tiers, and bolting a special case onto them
would blur a rule that is currently crisp. It bounds the two properties that
actually make an index usable — total size and per-row scannability — and
nothing else.

**A row is a pointer, not a summary.** The full rationale belongs in the linked
``PLAN.md``; keeping a copy in the index means maintaining the same paragraph in
two places, and the copy is the one that goes stale.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX = REPO_ROOT / "CLAUDE" / "Plan" / "README.md"

# Ceilings, not targets. Chosen with ~200 plans indexed and roughly 40% of
# headroom left, so ordinary growth never trips them and a return to
# paragraph-per-row does.
MAX_BYTES = 130_000
MAX_LINE_CHARS = 500


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
