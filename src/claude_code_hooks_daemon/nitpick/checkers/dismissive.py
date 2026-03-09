"""DismissiveLanguageChecker - Nitpick checker for dismissive language.

Reuses patterns from the Stop-event DismissiveLanguageDetectorHandler
to enforce single source of truth for pattern definitions.
"""

import re

from claude_code_hooks_daemon.handlers.stop.dismissive_language_detector import (
    DismissiveLanguageDetectorHandler,
)
from claude_code_hooks_daemon.nitpick.protocol import NitpickFinding

_CHECKER_ID = "dismissive_language"

# Category name -> pattern list, imported from the Stop handler
_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("not_our_problem", DismissiveLanguageDetectorHandler.NOT_OUR_PROBLEM_PATTERNS),
    ("out_of_scope", DismissiveLanguageDetectorHandler.OUT_OF_SCOPE_PATTERNS),
    ("someone_elses_job", DismissiveLanguageDetectorHandler.SOMEONE_ELSES_JOB_PATTERNS),
    ("defer_ignore", DismissiveLanguageDetectorHandler.DEFER_IGNORE_PATTERNS),
]


class DismissiveLanguageChecker:
    """Nitpick checker that detects dismissive language in assistant text.

    Scans for patterns indicating the agent is deflecting responsibility,
    scoping out issues, deferring work, or blaming others.

    Imports patterns from DismissiveLanguageDetectorHandler (Stop handler)
    to maintain a single source of truth.
    """

    checker_id: str = _CHECKER_ID

    def __init__(self) -> None:
        """Compile patterns once at init for performance."""
        self._compiled: list[tuple[str, str, re.Pattern[str]]] = []
        for category, patterns in _CATEGORY_PATTERNS:
            for pattern_str in patterns:
                self._compiled.append(
                    (category, pattern_str, re.compile(pattern_str, re.IGNORECASE))
                )

    def check(self, text: str) -> list[NitpickFinding]:
        """Scan text for dismissive language patterns.

        Args:
            text: Text content to audit

        Returns:
            List of NitpickFinding for each matched pattern
        """
        if not text:
            return []

        findings: list[NitpickFinding] = []
        for category, pattern_str, compiled in self._compiled:
            if compiled.search(text):
                findings.append(
                    NitpickFinding(
                        checker_id=_CHECKER_ID,
                        category=category,
                        message=f"Dismissive language detected: {category.replace('_', ' ')}",
                        matched_pattern=pattern_str,
                    )
                )
        return findings
