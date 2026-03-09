"""HedgingLanguageChecker - Nitpick checker for hedging language.

Reuses patterns from the Stop-event HedgingLanguageDetectorHandler
to enforce single source of truth for pattern definitions.
"""

import re

from claude_code_hooks_daemon.handlers.stop.hedging_language_detector import (
    HedgingLanguageDetectorHandler,
)
from claude_code_hooks_daemon.nitpick.protocol import NitpickFinding

_CHECKER_ID = "hedging_language"

# Category name -> pattern list, imported from the Stop handler
_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("memory_guessing", HedgingLanguageDetectorHandler.MEMORY_PATTERNS),
    ("uncertainty", HedgingLanguageDetectorHandler.UNCERTAINTY_PATTERNS),
    ("weak_confidence", HedgingLanguageDetectorHandler.WEAK_CONFIDENCE_PATTERNS),
]


class HedgingLanguageChecker:
    """Nitpick checker that detects hedging language in assistant text.

    Scans for patterns indicating the agent is guessing instead of
    researching — relying on memory, expressing uncertainty about
    verifiable facts, or hedging with weak confidence.

    Imports patterns from HedgingLanguageDetectorHandler (Stop handler)
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
        """Scan text for hedging language patterns.

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
                        message=f"Hedging language detected: {category.replace('_', ' ')}",
                        matched_pattern=pattern_str,
                    )
                )
        return findings
