"""ReadmeIndex — parser for the plan directory's ``README.md`` index.

Parses the index into section-classified rows plus the statistics bullets,
covering BOTH real-world grammars (Plan 00144):

- linked rows: ``- [NNNNN: Title](path/PLAN.md) - Status text`` — optionally
  grouped under ``###`` category subsections that inherit the enclosing
  ``##`` section
- linkless bold rows (sin B7): ``- **00008** - Complete`` and multi-number
  rows like ``- **00032, 00034, 00035** - On hold ...``
- statistics bullets: ``- **Label**: N (free text)`` — the leading integer is
  extracted; non-numeric bullets are skipped

Only TOP-LEVEL list items are rows: indented detail bullets under a row are
prose, even when they contain plan links. Fenced code blocks are ignored via
the shared :func:`plan_qa.model.lines_outside_fences` helper, and the parser
tolerates mdformat-gfm output (markdown_table_formatter compatibility).
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Final

from claude_code_hooks_daemon.plan_qa.model import lines_outside_fences


class ReadmeSection(str, Enum):
    """Which index section a row was found under."""

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    STATISTICS = "statistics"
    OTHER = "other"


# Keyword → section classification for ``##`` headings, checked in order so
# "Blocked / On Hold Plans" resolves before any broader match could.
_SECTION_KEYWORDS: Final[tuple[tuple[str, ReadmeSection], ...]] = (
    ("statistic", ReadmeSection.STATISTICS),
    ("blocked", ReadmeSection.BLOCKED),
    ("on hold", ReadmeSection.BLOCKED),
    ("cancelled", ReadmeSection.CANCELLED),
    ("completed", ReadmeSection.COMPLETED),
    ("active", ReadmeSection.ACTIVE),
)

_H2_RE: Final[re.Pattern[str]] = re.compile(r"^##(?!#)\s+(.+?)\s*$")

# ``- [NNNNN<decoration>: Title](link) - status``; status separator accepts
# hyphen and en/em dashes because prose (and mdformat) vary.
_LINKED_ROW_RE: Final[re.Pattern[str]] = re.compile(
    r"^- \[(\d{1,5})([^\]]*)\]\(([^)]+)\)\s*(?:[-–—]\s*(.*?))?\s*$"
)

# ``- **00008** - status`` / ``- **00032, 00034, 00035** - status``
_BOLD_ROW_RE: Final[re.Pattern[str]] = re.compile(r"^- \*\*([^*]+)\*\*\s*(?:[-–—]\s*(.*?))?\s*$")

# ``- **Label**: 42 (free text)`` — statistics bullets.
_STAT_RE: Final[re.Pattern[str]] = re.compile(r"^- \*\*([^*]+)\*\*\s*:\s*(\d+)")

_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"\b(\d{1,5})\b")

_TITLE_LEADING_COLON_RE: Final[re.Pattern[str]] = re.compile(r"^\s*:?\s*")


@dataclass(frozen=True)
class ReadmeRow:
    """One top-level index row (usually one plan; blocked rows may list several)."""

    numbers: tuple[int, ...]
    title: str | None
    link: str | None
    status_text: str | None
    section: ReadmeSection


@dataclass(frozen=True)
class ReadmeIndex:
    """Parsed view of a plan-index README."""

    rows: tuple[ReadmeRow, ...]
    stats: dict[str, int]

    @classmethod
    def parse(cls, text: str) -> "ReadmeIndex":
        """Parse ``text`` (full README.md content) into a :class:`ReadmeIndex`."""
        rows: list[ReadmeRow] = []
        stats: dict[str, int] = {}
        section = ReadmeSection.OTHER

        for line in lines_outside_fences(text):
            heading = _H2_RE.match(line)
            if heading:
                section = _classify_section(heading.group(1))
                continue

            if section == ReadmeSection.STATISTICS:
                stat = _STAT_RE.match(line)
                if stat:
                    stats[stat.group(1).strip()] = int(stat.group(2))
                continue

            row = _parse_row(line, section)
            if row is not None:
                rows.append(row)

        return cls(rows=tuple(rows), stats=stats)

    def rows_for(self, number: int) -> tuple[ReadmeRow, ...]:
        """Every row that references plan ``number``."""
        return tuple(row for row in self.rows if number in row.numbers)

    def numbers(self) -> frozenset[int]:
        """All plan numbers referenced by any row."""
        return frozenset(number for row in self.rows for number in row.numbers)


def _classify_section(heading: str) -> ReadmeSection:
    """Map a ``##`` heading to a :class:`ReadmeSection` by keyword."""
    lowered = heading.lower()
    for keyword, section in _SECTION_KEYWORDS:
        if keyword in lowered:
            return section
    return ReadmeSection.OTHER


def _parse_row(line: str, section: ReadmeSection) -> ReadmeRow | None:
    """Parse one top-level list item into a row, or ``None`` for prose.

    Indented list items are detail bullets, never rows — both grammars
    require the line to start at column zero.
    """
    linked = _LINKED_ROW_RE.match(line)
    if linked:
        title = _TITLE_LEADING_COLON_RE.sub("", linked.group(2)).strip() or None
        return ReadmeRow(
            numbers=(int(linked.group(1)),),
            title=title,
            link=linked.group(3),
            status_text=linked.group(4) or None,
            section=section,
        )

    bold = _BOLD_ROW_RE.match(line)
    if bold:
        numbers = tuple(int(value) for value in _NUMBER_RE.findall(bold.group(1)))
        if not numbers:
            return None
        return ReadmeRow(
            numbers=numbers,
            title=None,
            link=None,
            status_text=bold.group(2) or None,
            section=section,
        )

    return None
