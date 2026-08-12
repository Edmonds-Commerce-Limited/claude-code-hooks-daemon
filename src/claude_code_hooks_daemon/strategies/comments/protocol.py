"""Comment Strategy Protocol - interface for language-specific comment syntax."""

from typing import Any, Protocol, runtime_checkable

from claude_code_hooks_daemon.strategies.comments.syntax import CommentSyntax


@runtime_checkable
class CommentStrategy(Protocol):
    """Strategy interface for language-specific comment syntax.

    Each implementation supplies ONLY data: which extensions it applies to,
    its comment syntax (line prefixes, block/doc delimiters), and which
    directories to skip. Extraction and matching logic live once, shared,
    in ``extractor.py`` and the ``comment_size``/``comment_changelog``
    handlers -- strategies carry zero behaviour, mirroring how
    ``QaSuppressionStrategy`` carries only ``forbidden_patterns``.

    To add a new language: implement this Protocol and register in
    ``CommentStrategyRegistry.create_default()``.
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
    def syntax(self) -> CommentSyntax:
        """Comment syntax (line prefixes, block/doc delimiters) for this language."""
        ...

    @property
    def skip_directories(self) -> tuple[str, ...]:
        """Directories to skip (vendor, build, node_modules, etc.)."""
        ...

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this language strategy."""
        ...
