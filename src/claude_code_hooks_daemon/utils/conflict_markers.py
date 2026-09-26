"""Merge-conflict marker detection, raw and formatter-disguised (Plan 00466 N211).

git writes a conflict as three or four column-0 marker lines: an opener of
``<``, an optional diff3 base of ``|``, a separator of ``=`` and a closer of
``>``. Each is a run of seven characters unless the path's
``conflict-marker-size`` attribute names another length, so every function
here takes that ``size``.

Two of those shapes stop looking like markers once the markdown formatter has
run over them. The opener comes back escaped (``\\<<\\<<\\<<<``, or
``\\<<\\<<\\<<\\<`` when it has no label), wherever the formatter put it: alone,
in a heading that swallowed the paragraph above, in a blockquote, a list item
or a table cell. The closer comes back as a blockquote ``size`` levels deep,
``>`` repeated with spaces between. A marker in that form is invisible to
every check that looks for the raw shape, which is how two closers reached
ledger 00466's NIGGLES.md.

A line of ``=`` is also a legitimate setext heading underline, and a line of
``|`` can be an empty table row, so those two count only between an opener and
a closer. A deep blockquote is also legitimate email-style quoting, so it
counts on its own only in the shape git writes a closer: exactly ``size``
deep, with no label or a one-word label (a branch). Any other deep quote is a
closer only after an opener and a separator. Openers and raw closers always
count.

This module is the single classifier. The commit gate narrows its search
with :func:`git_grep_prefilter` first, which is deliberately LOOSER than the
classifier, and every line it returns is judged here.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from typing import Final

#: git's marker length when no ``conflict-marker-size`` attribute applies.
DEFAULT_MARKER_SIZE: Final[int] = 7


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


@dataclass(frozen=True)
class _Shape:
    """A marker-shaped line. ``region_only`` ones count only inside a conflict."""

    kind: MarkerKind
    disguised: bool
    region_only: bool


@dataclass(frozen=True)
class _Patterns:
    """Every marker spelling for one marker size."""

    raw: tuple[tuple[MarkerKind, re.Pattern[str]], ...]
    disguised: tuple[tuple[MarkerKind, re.Pattern[str]], ...]
    escaped_open: re.Pattern[str]
    quoted_close: re.Pattern[str]
    branch_close: re.Pattern[str]


# The label git appends after an opener, base or closer: nothing, or a space
# and the rest of the line.
_LABEL: Final[str] = r"(?: .*)?"
# A label git writes on a merge closer: one word, and not a deeper quote.
_BRANCH_LABEL: Final[str] = r"(?: [^\s>]\S*)?"
# Leading whitespace is allowed on a disguised marker only: git always writes
# column 0, but the formatter indents a marker it folded into a list item.
_INDENT: Final[str] = r"[ \t]*"
_BACKTICK: Final[str] = "`"


@cache
def _patterns(size: int) -> _Patterns:
    if size < 1:
        raise ValueError(f"conflict marker size must be at least 1, got {size}")
    before = size - 1
    return _Patterns(
        raw=(
            (MarkerKind.OPEN, re.compile(rf"<{{{size}}}{_LABEL}")),
            (MarkerKind.BASE, re.compile(rf"\|{{{size}}}{_LABEL}")),
            (MarkerKind.SEPARATOR, re.compile(rf"={{{size}}}")),
            (MarkerKind.CLOSE, re.compile(rf">{{{size}}}{_LABEL}")),
        ),
        disguised=(
            (MarkerKind.OPEN, re.compile(rf"{_INDENT}(?:< ){{{before}}}<{_LABEL}")),
            (MarkerKind.SEPARATOR, re.compile(rf"{_INDENT}\\={{{size}}}")),
        ),
        # A whole word of exactly ``size`` `<`, each optionally escaped, the
        # first always: the formatter escapes the run wherever it lands.
        escaped_open=re.compile(rf"(?:^|(?<=[ \t]))\\<(?:\\?<){{{before}}}(?=[ \t]|$)"),
        quoted_close=re.compile(rf"{_INDENT}(?:> ){{{before}}}>{_LABEL}"),
        branch_close=re.compile(rf"{_INDENT}(?:> ){{{before}}}>{_BRANCH_LABEL}"),
    )


def git_grep_prefilter(size: int) -> str:
    """A POSIX ERE for ``git grep -E`` matching every marker line of ``size`` or more.

    It also matches lines :func:`classify_marker_line` rejects; the classifier
    has the last word. A literal pipe is written ``[|]`` because ``\\|`` is
    alternation in GNU ERE.
    """
    _patterns(size)
    before = size - 1
    return (
        rf"^[[:space:]]*(<{{{size},}}|>{{{size},}}|[|]{{{size},}}|={{{size},}}|\\={{{size},}}"
        rf"|(< ){{{before},}}<|(> ){{{before},}}>)"
        rf"|\\<(\\?<){{{before},}}"
    )


#: :func:`git_grep_prefilter` at the default marker size.
GIT_GREP_PREFILTER: Final[str] = git_grep_prefilter(DEFAULT_MARKER_SIZE)

# Separator-like kinds are only markers inside an opener/closer pair.
_REGION_ONLY: Final[frozenset[MarkerKind]] = frozenset({MarkerKind.BASE, MarkerKind.SEPARATOR})
_LINE_END: Final[str] = "\r\n"


def _outside_code_span(line: str, position: int) -> bool:
    """Whether ``position`` sits outside an inline code span (even backticks before it)."""
    return line.count(_BACKTICK, 0, position) % 2 == 0


def _shape(line: str, size: int) -> _Shape | None:
    stripped = line.rstrip(_LINE_END)
    patterns = _patterns(size)
    for kind, pattern in patterns.raw:
        if pattern.fullmatch(stripped):
            return _Shape(kind, disguised=False, region_only=kind in _REGION_ONLY)
    for kind, pattern in patterns.disguised:
        if pattern.fullmatch(stripped):
            return _Shape(kind, disguised=True, region_only=kind in _REGION_ONLY)
    if patterns.branch_close.fullmatch(stripped):
        return _Shape(MarkerKind.CLOSE, disguised=True, region_only=False)
    if patterns.quoted_close.fullmatch(stripped):
        return _Shape(MarkerKind.CLOSE, disguised=True, region_only=True)
    for match in patterns.escaped_open.finditer(stripped):
        if _outside_code_span(stripped, match.start()):
            return _Shape(MarkerKind.OPEN, disguised=True, region_only=False)
    return None


def classify_marker_line(
    line: str, size: int = DEFAULT_MARKER_SIZE
) -> tuple[MarkerKind, bool] | None:
    """``(kind, disguised)`` when ``line`` has a conflict marker's shape, else None.

    Says nothing about position: a separator-shaped line, or a deep quote, is
    returned here whether or not it sits inside a conflict.
    :func:`find_conflict_markers` applies that rule.
    """
    shape = _shape(line, size)
    return None if shape is None else (shape.kind, shape.disguised)


def find_conflict_markers(
    numbered_lines: Iterable[tuple[int, str]], size: int = DEFAULT_MARKER_SIZE
) -> list[ConflictMarker]:
    """The conflict markers among ``numbered_lines``, in line order.

    ``numbered_lines`` may be a whole file or only its marker-shaped lines:
    the region rule needs the openers and closers, not the lines between.
    A base or separator counts only when an opener precedes it and a closer
    follows it before the next opener. A deep quote that is not a closer on
    its own counts only after an opener and a separator.

    Raises:
        ValueError: ``size`` is below 1.
    """
    _patterns(size)
    found: list[ConflictMarker] = []
    pending: list[ConflictMarker] = []
    inside = False
    for line_number, line in sorted(numbered_lines):
        shape = _shape(line, size)
        if shape is None:
            continue
        marker = ConflictMarker(
            line_number=line_number,
            kind=shape.kind,
            disguised=shape.disguised,
            text=line.rstrip(_LINE_END),
        )
        if shape.region_only and shape.kind is not MarkerKind.CLOSE:
            if inside:
                pending.append(marker)
            continue
        if shape.region_only and not any(m.kind is MarkerKind.SEPARATOR for m in pending):
            continue
        if shape.kind is MarkerKind.OPEN:
            pending = []
            inside = True
        elif inside:
            found.extend(pending)
            pending = []
            inside = False
        found.append(marker)
    found.sort(key=lambda marker: marker.line_number)
    return found


def find_conflict_markers_in_text(
    text: str, size: int = DEFAULT_MARKER_SIZE
) -> list[ConflictMarker]:
    """The conflict markers in a whole document, numbered from line 1."""
    return find_conflict_markers(enumerate(text.splitlines(), start=1), size)


def describe_markers(markers: Iterable[ConflictMarker]) -> str:
    """One line per marker, naming its line number, its kind and its text."""
    rows: list[str] = []
    for marker in markers:
        spelling = "disguised by the markdown formatter" if marker.disguised else "raw"
        rows.append(
            f"  line {marker.line_number}: {marker.kind} marker ({spelling}): {marker.text}"
        )
    return "\n".join(rows)
