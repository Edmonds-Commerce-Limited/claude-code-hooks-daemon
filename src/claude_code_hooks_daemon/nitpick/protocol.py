"""NitpickChecker protocol and supporting data types.

Defines the Protocol interface for nitpick checkers (lightweight quality
auditors) and the data classes they produce and consume.

Usage:
    class MyChecker:
        checker_id = "my_checker"

        def check(self, text: str) -> list[NitpickFinding]:
            # Scan text for quality issues
            return [NitpickFinding(...)] if issues else []
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class NitpickFinding:
    """A single quality issue found by a nitpick checker.

    Attributes:
        checker_id: ID of the checker that produced this finding
        category: Issue category (e.g. "deflection", "hedging")
        message: Human-readable description of the issue
        matched_pattern: The pattern or text that triggered the finding
    """

    checker_id: str
    category: str
    message: str
    matched_pattern: str


@dataclass(slots=True)
class NitpickState:
    """Mutable state for incremental transcript auditing.

    Persisted in DaemonDataLayer (in-memory, keyed by session_id).
    Reset on context compaction.

    Attributes:
        last_byte_offset: File seek position for incremental reading
        last_audited_uuid: UUID of last audited transcript message
        findings_count: Running count of findings this session
    """

    last_byte_offset: int = 0
    last_audited_uuid: str | None = None
    findings_count: int = 0


@runtime_checkable
class NitpickChecker(Protocol):
    """Protocol for nitpick checker strategies.

    Checkers are lightweight pattern matchers that scan text for quality
    issues. They don't need handler infrastructure (tags, priority, terminal
    flags) — those belong to the NitpickHandler that orchestrates them.

    Adding a new checker = one class with patterns. No wiring needed.
    """

    checker_id: str

    def check(self, text: str) -> list[NitpickFinding]:
        """Scan text for quality issues.

        Args:
            text: Text content to audit (typically assistant message content)

        Returns:
            List of findings, empty if no issues detected
        """
        ...
