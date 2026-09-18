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


def lines_outside_fences(text: str) -> list[str]:
    """Split ``text`` into lines, dropping everything inside fenced blocks.

    Fence delimiter lines themselves are also dropped. Unclosed fences swallow
    the remainder of the document — the safe failure mode for counting.
    """
    result: list[str] = []
    in_fence = False
    fence_marker: str | None = None
    for line in text.splitlines():
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = None
            continue
        if not in_fence:
            result.append(line)
    return result
