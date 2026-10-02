"""Defence Before Fix (DBF) constants.

The method this project's handlers follow is published at
``DefenceBeforeFix.URL``. The URL and the one-line pointer printed by
``explain-rule`` and ``explain-handler`` live here so each appears once.
"""

from __future__ import annotations

from typing import ClassVar


class DefenceBeforeFix:
    """Public home of the Defence Before Fix method and its CLI pointer line."""

    URL: ClassVar[str] = "https://defence-before-fix.github.io"
    EXPLAIN_LINE: ClassVar[str] = (
        f"Defence Before Fix: this is a defence in the DBF sense. Method: {URL}"
    )
