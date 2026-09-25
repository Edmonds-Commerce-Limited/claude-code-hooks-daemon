"""Fenced-code-block splitting, shared by both QA subsystems.

Every line-oriented markdown check in this project needs the same first step:
drop what is inside ``` or ~~~ blocks, so that a document QUOTING a checkbox,
a link or an ``@import`` is not read as one that USES it.

It lives in ``utils`` because three unrelated callers need it — plan QA's
parsers, docs QA's import census, and the shared link extractor next door —
and a primitive owned by one subsystem that the others import is how the
dependency direction ends up the reverse of what the code says it is.
"""

import re
from typing import Final

_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(```|~~~)")


def line_spans_outside_fences(text: str) -> list[tuple[int, int, str]]:
    """Like :func:`lines_outside_fences`, but also returns each surviving
    line's ``(start, end)`` character offset in ``text`` (end exclusive,
    excluding the line's own newline).

    A caller that needs to know WHERE a kept line sits in the original
    string — not just its content — reuses this instead of re-deriving
    fence tracking itself (Plan 00466 RV3-m1: the ``replace_all`` flip
    ambiguity check needs to tell whether a matched offset falls on the
    real, non-fenced Status line).
    """
    result: list[tuple[int, int, str]] = []
    in_fence = False
    fence_marker: str | None = None
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        content = raw_line.splitlines()[0] if raw_line.splitlines() else raw_line
        end = offset + len(content)
        fence_match = _FENCE_RE.match(content)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = None
        elif not in_fence:
            result.append((offset, end, content))
        offset += len(raw_line)
    return result


def lines_outside_fences(text: str) -> list[str]:
    """Split ``text`` into lines, dropping everything inside fenced blocks.

    Fence delimiter lines themselves are also dropped. Unclosed fences swallow
    the remainder of the document — the safe failure mode for counting.
    """
    return [content for _, _, content in line_spans_outside_fences(text)]
