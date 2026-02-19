"""PipeBlockerStrategy Protocol - interface for language-specific blacklist patterns."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PipeBlockerStrategy(Protocol):
    """Strategy interface for language-specific pipe-to-tail/head blacklists.

    Each implementation encapsulates ALL language-specific logic for:
    - Identifying expensive commands that should never be piped to tail/head
    - Providing blacklist regex patterns for command matching

    Patterns are matched against the FULL source segment (not just the first word),
    enabling multi-word patterns like r'^npm\\s+test\\b' or r'^go\\s+build\\b'.

    To add a new language: implement this Protocol and register in PipeBlockerStrategyRegistry.
    """

    @property
    def language_name(self) -> str:
        """Human-readable language name (e.g., 'Python', 'Universal')."""
        ...

    @property
    def blacklist_patterns(self) -> tuple[str, ...]:
        """Regex patterns for commands that should NEVER be piped to tail/head.

        Each pattern is matched against the full source segment with re.IGNORECASE.
        Multi-word patterns like r'^npm\\s+test\\b' are fully supported.
        """
        ...

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this language strategy.

        MANDATORY: every strategy must return at least one test.
        Tests should use TestType.BLOCKING with expected_decision=Decision.DENY.
        """
        ...
