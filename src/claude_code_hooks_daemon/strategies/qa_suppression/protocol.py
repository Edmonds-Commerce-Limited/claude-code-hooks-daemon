"""QA Suppression Strategy Protocol - interface for language-specific QA suppression."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class QaSuppressionStrategy(Protocol):
    """Strategy interface for language-specific QA suppression enforcement.

    Each implementation encapsulates ALL language-specific logic for:
    - Identifying forbidden QA suppression patterns
    - Identifying directories to skip (vendor, build, etc.)
    - Providing QA tool names and documentation URLs for error messages

    To add a new language: implement this Protocol and register in
    QaSuppressionStrategyRegistry.
    """

    @property
    def language_name(self) -> str:
        """Human-readable language name for error messages."""
        ...

    @property
    def extensions(self) -> tuple[str, ...]:
        """File extensions handled by this strategy (e.g., ('.py',))."""
        ...

    @property
    def forbidden_patterns(self) -> tuple[str, ...]:
        """Regex patterns for QA suppression comments to block."""
        ...

    @property
    def skip_directories(self) -> tuple[str, ...]:
        """Directories to skip (vendor, build, etc.)."""
        ...

    @property
    def tool_names(self) -> tuple[str, ...]:
        """QA tool names for error messages."""
        ...

    @property
    def tool_docs_urls(self) -> tuple[str, ...]:
        """Documentation URLs for QA tools."""
        ...

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this language strategy."""
        ...
