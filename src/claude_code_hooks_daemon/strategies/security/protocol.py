"""SecurityStrategy Protocol - interface for language-specific security antipatterns.

Defines the contract that every security strategy must satisfy.
The handler delegates ALL language-specific logic to strategies; it has
zero awareness of individual languages.
"""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SecurityPattern:
    """A single security antipattern to detect and block.

    Attributes:
        name: Short human-readable label (e.g. "AWS Access Key").
        regex: Raw regex string matched against file content.
        owasp: OWASP category code (e.g. "A02", "A03").
        suggestion: What to do instead of this pattern.
    """

    name: str
    regex: str
    owasp: str
    suggestion: str


@runtime_checkable
class SecurityStrategy(Protocol):
    """Strategy interface for language-specific security antipattern detection.

    Each implementation encapsulates ALL language-specific logic for:
    - Identifying which file extensions belong to this language.
    - Providing the patterns that constitute security antipatterns.

    Universal strategies (e.g. secret detection) use extensions = ("*",)
    to indicate they apply to ALL file types regardless of extension.

    Patterns are matched against the FULL new file content (Write tool) or
    the new_string fragment (Edit tool).

    To add a new language: implement this Protocol and register in
    SecurityStrategyRegistry.
    """

    @property
    def language_name(self) -> str:
        """Human-readable language name (e.g. 'PHP', 'JavaScript')."""
        ...

    @property
    def extensions(self) -> tuple[str, ...]:
        """File extensions handled by this strategy.

        Use ("*",) for universal strategies that apply to all file types
        (e.g. secret detection).
        """
        ...

    @property
    def patterns(self) -> tuple[SecurityPattern, ...]:
        """Patterns that constitute security antipatterns in this language.

        Each pattern's regex is matched against the content.
        All matching patterns are collected and reported.
        """
        ...

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this language strategy.

        MANDATORY: every strategy must return at least one BLOCKING test
        (pattern detected -> DENY).
        """
        ...
