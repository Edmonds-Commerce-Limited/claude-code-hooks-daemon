"""Merge-conflict marker detection, raw and formatter-disguised (Plan 00466 N211).

git writes a conflict as three or four column-0 marker lines: an opener of
seven ``<``, an optional diff3 base of seven ``|``, a separator of seven
``=`` and a closer of seven ``>``. Two of those shapes stop looking like
markers once the markdown formatter has run over them: the opener comes back
as ``\\<<\\<<\\<<<`` (escaped, sometimes folded into a heading or a table cell)
and the closer as a seven-deep blockquote, ``>`` repeated seven times with
spaces between. A marker in that form is invisible to every check that looks
for the raw shape, which is how two closers reached ledger 00466's NIGGLES.md.

A line of seven ``=`` is also a legitimate setext heading underline, and a
line of seven ``|`` can be an empty table row, so those two count only when
they sit between an opener and a closer. Openers and closers always count.

This module is the single classifier. The commit gate narrows its search
with :data:`GIT_GREP_PREFILTER` first, which is deliberately LOOSER than the
classifier, and every line it returns is judged here.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class MarkerKind(StrEnum):
    """Which of git's conflict marker lines a line is."""

    OPEN = "open"
    BASE = "base"
    SEPARATOR = "separator"
    CLOSE = "close"


@dataclass(frozen=True)
class ConflictMarker:
    """One conflict marker line: where it is, what it is, and its text."""

    line_number: int
    kind: MarkerKind
    disguised: bool
    text: str


# The label git appends after an opener, base or closer: nothing, or a space
# and the rest of the line.
_LABEL: Final[str] = r"(?: .*)?"
# Leading whitespace is allowed on a disguised marker only: git always writes
# column 0, but the formatter indents a marker it folded into a list item.
_INDENT: Final[str] = r"[ \t]*"
# The formatter folds an escaped opener into a heading or a table cell.
_FOLDED_PREFIX: Final[str] = r"(?:#{1,6} |\| )?"

_RAW_PATTERNS: Final[tuple[tuple[MarkerKind, re.Pattern[str]], ...]] = (
    (MarkerKind.OPEN, re.compile(rf"<{{7}}{_LABEL}")),
    (MarkerKind.BASE, re.compile(rf"\|{{7}}{_LABEL}")),
    (MarkerKind.SEPARATOR, re.compile(r"={7}")),
    (MarkerKind.CLOSE, re.compile(rf">{{7}}{_LABEL}")),
)
_DISGUISED_PATTERNS: Final[tuple[tuple[MarkerKind, re.Pattern[str]], ...]] = (
    (
        MarkerKind.OPEN,
        re.compile(rf"{_INDENT}{_FOLDED_PREFIX}(?:\\<<\\<<\\<<<|(?:< ){{6}}<){_LABEL}"),
    ),
    (MarkerKind.SEPARATOR, re.compile(rf"{_INDENT}\\={{7}}")),
    (MarkerKind.CLOSE, re.compile(rf"{_INDENT}(?:> ){{6}}>{_LABEL}")),
)

#: A POSIX ERE for ``git grep -E`` that matches every line
#: :func:`classify_marker_line` accepts, and some it does not. A literal pipe
#: is written ``[|]`` because ``\\|`` is alternation in GNU ERE.
GIT_GREP_PREFILTER: Final[str] = (
    r"^[[:space:]]*(<{7}|>{7}|[|]{7}|={7}|\\={7}"
    r"|(#{1,6} |[|] )?(\\<<\\<<\\<<<|(< ){6}<)|(> ){6}>)"
)

# Separator-like kinds are only markers inside an opener/closer pair.
_REGION_ONLY: Final[frozenset[MarkerKind]] = frozenset({MarkerKind.BASE, MarkerKind.SEPARATOR})
_LINE_END: Final[str] = "\r\n"


def classify_marker_line(line: str) -> tuple[MarkerKind, bool] | None:
    """``(kind, disguised)`` when ``line`` has a conflict marker's shape, else None.

    Says nothing about position: a separator-shaped line is returned here
    whether or not it sits inside a conflict. :func:`find_conflict_markers`
    applies that rule.
    """
    stripped = line.rstrip(_LINE_END)
    for kind, pattern in _RAW_PATTERNS:
        if pattern.fullmatch(stripped):
            return kind, False
    for kind, pattern in _DISGUISED_PATTERNS:
        if pattern.fullmatch(stripped):
            return kind, True
    return None


def find_conflict_markers(numbered_lines: Iterable[tuple[int, str]]) -> list[ConflictMarker]:
    """The conflict markers among ``numbered_lines``, in line order.

    ``numbered_lines`` may be a whole file or only its marker-shaped lines:
    the region rule needs the openers and closers, not the lines between.
    A base or separator counts only when an opener precedes it and a closer
    follows it before the next opener.
    """
    found: list[ConflictMarker] = []
    pending: list[ConflictMarker] = []
    inside = False
    for line_number, line in sorted(numbered_lines):
        shape = classify_marker_line(line)
        if shape is None:
            continue
        kind, disguised = shape
        marker = ConflictMarker(
            line_number=line_number,
            kind=kind,
            disguised=disguised,
            text=line.rstrip(_LINE_END),
        )
        if kind in _REGION_ONLY:
            if inside:
                pending.append(marker)
            continue
        if kind is MarkerKind.OPEN:
            pending = []
            inside = True
        elif inside:
            found.extend(pending)
            pending = []
            inside = False
        found.append(marker)
    found.sort(key=lambda marker: marker.line_number)
    return found


def find_conflict_markers_in_text(text: str) -> list[ConflictMarker]:
    """The conflict markers in a whole document, numbered from line 1."""
    return find_conflict_markers(enumerate(text.splitlines(), start=1))


def describe_markers(markers: Iterable[ConflictMarker]) -> str:
    """One line per marker, naming its line number, its kind and its text."""
    rows: list[str] = []
    for marker in markers:
        spelling = "disguised by the markdown formatter" if marker.disguised else "raw"
        rows.append(
            f"  line {marker.line_number}: {marker.kind} marker ({spelling}): {marker.text}"
        )
    return "\n".join(rows)
