"""Find a plan by NAME, across the whole plan tree (ledger 00413 N7).

``plan_number_helper`` denies a folder scan of the plan directory, and it is
right to: such a scan reaches the active plans and misses everything archived
under ``Completed/``, so it can report "not found" about a plan that exists.

What the guard leaves behind is an AFFORDANCE gap rather than a false
positive. Its deny message answers with the next plan NUMBER — which is the
answer to a different question from "where is the Jobs plan". Before this
module the only routes were ``git ls-files`` (which happens to work, and is
documented nowhere) or dispatching the dedupe-scout agent (right before filing
a plan, wrong for a lookup).

This reads the FILESYSTEM, deliberately, rather than ``README.md``'s index.
The index is more convenient and is normally complete — ``plan_qa``'s
``row-folder-bijection`` check exists to keep it so — but "normally" is the
problem. A plan whose row is missing would be invisible to a reader who had
been told the search covers everything, which is the guard's own failure mode
reintroduced one layer up. The filesystem cannot have that gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_PLAN_DOCUMENT: Final[str] = "PLAN.md"

# A plan folder is NNNNN-name. Only the NUMBER is required here, deliberately:
# a folder this finder cannot fully parse is still FOUND rather than hidden,
# because hiding it would reproduce the very failure the guard prevents.
_PLAN_FOLDER: Final[re.Pattern[str]] = re.compile(r"^(\d{4,5})-")

_STATUS_LINE: Final[re.Pattern[str]] = re.compile(r"^\*\*Status\*\*:\s*(.+?)\s*$", re.MULTILINE)
_TITLE_LINE: Final[re.Pattern[str]] = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

# Only the header carries title and status, and a plan document can run to
# hundreds of lines. Reading a bounded prefix keeps a search over ~400 plans
# cheap enough to be reached for casually, which is the point of the tool.
_HEADER_BYTES: Final[int] = 2048


@dataclass(frozen=True)
class PlanMatch:
    """One plan the query matched."""

    number: int
    path: str
    title: str | None
    status: str | None


def _read_header(plan_document: Path) -> str:
    """Return the first chunk of a plan document, or empty on a read failure.

    A file that cannot be read must not abort a search over the whole tree:
    the other matches are still correct and useful, and a finder that raises
    on one unreadable file is one nobody reaches for. The plan is still
    reported — with no title and no status — so it cannot go missing.
    """
    try:
        with plan_document.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(_HEADER_BYTES)
    except OSError:
        return ""


def _first_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


def find_plans(project_root: Path, plan_dir: str, query: str) -> list[PlanMatch]:
    """Every plan whose number, folder name or title matches ``query``.

    Args:
        project_root: Repository root; ``plan_dir`` is resolved beneath it.
        plan_dir: Repo-relative plan directory (e.g. ``CLAUDE/Plan``).
        query: Free text, a plan number, or empty to list every plan.

    Returns:
        Matches ordered by plan number. Empty when nothing matches and when
        the plan directory is absent — a project with no plans yet is a
        legitimate state, not an error.
    """
    root = project_root / plan_dir
    if not root.is_dir():
        return []

    needle = query.strip().lower()
    # A bare number and a zero-padded one must find the same plan, so the
    # numeric form is compared as a NUMBER rather than as a substring:
    # "412" must not match plan 04120 by accident.
    numeric = int(needle) if needle.isdigit() else None

    matches: list[PlanMatch] = []
    for plan_document in root.rglob(_PLAN_DOCUMENT):
        folder = plan_document.parent
        number_match = _PLAN_FOLDER.match(folder.name)
        if number_match is None:
            continue

        number = int(number_match.group(1))
        header = _read_header(plan_document)
        title = _first_group(_TITLE_LINE, header)

        haystack = f"{folder.name} {title or ''}".lower()
        if needle and numeric != number and needle not in haystack:
            continue

        matches.append(
            PlanMatch(
                number=number,
                path=str(folder.relative_to(project_root)),
                title=title,
                status=_first_group(_STATUS_LINE, header),
            )
        )

    matches.sort(key=lambda match: (match.number, match.path))
    return matches
