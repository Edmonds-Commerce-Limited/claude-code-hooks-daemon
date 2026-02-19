"""ErrorHidingStrategy Protocol - interface for language-specific error-hiding patterns.

Defines the contract that every language strategy must satisfy.
The handler delegates ALL language-specific logic to strategies; it has
zero awareness of individual languages.
"""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ErrorHidingPattern:
    """A single error-hiding pattern to detect and block.

    Attributes:
        name: Short human-readable label (e.g. "|| true").
        regex: Raw regex string matched against file content with re.MULTILINE.
        example: A code snippet illustrating the bad pattern.
        suggestion: What to do instead of this pattern.
    """

    name: str
    regex: str
    example: str
    suggestion: str


@runtime_checkable
class ErrorHidingStrategy(Protocol):
    """Strategy interface for language-specific error-hiding pattern detection.

    Each implementation encapsulates ALL language-specific logic for:
    - Identifying which file extensions belong to this language.
    - Providing the patterns that constitute error-hiding in this language.

    Patterns are matched against the FULL new file content (Write tool) or
    the new_string fragment (Edit tool).

    To add a new language: implement this Protocol and register in
    ErrorHidingStrategyRegistry.
    """

    @property
    def language_name(self) -> str:
        """Human-readable language name (e.g. 'Python', 'Shell')."""
        ...

    @property
    def extensions(self) -> tuple[str, ...]:
        """File extensions handled by this strategy (e.g. ('.py',))."""
        ...

    @property
    def patterns(self) -> tuple[ErrorHidingPattern, ...]:
        """Patterns that constitute error-hiding in this language.

        Each pattern's regex is matched with re.MULTILINE against the content.
        The first matching pattern triggers a DENY decision.
        """
        ...

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this language strategy.

        MANDATORY: every strategy must return at least two tests —
        one BLOCKING (pattern detected → DENY) and one ADVISORY (clean
        code → ALLOW).
        """
        ...
