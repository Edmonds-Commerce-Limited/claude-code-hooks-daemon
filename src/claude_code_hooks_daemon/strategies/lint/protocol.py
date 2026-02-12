"""Lint Strategy Protocol - interface for language-specific lint enforcement."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LintStrategy(Protocol):
    """Strategy interface for language-specific lint enforcement.

    Each implementation encapsulates ALL language-specific logic for:
    - Default lint command (built-in linter, e.g., bash -n, python -m py_compile)
    - Extended lint command (optional extra tool, e.g., shellcheck, ruff)
    - File extensions handled
    - Paths to skip (vendor, build, etc.)

    Commands use {file} placeholder, replaced at runtime with actual file path.

    To add a new language: implement this Protocol and register in LintStrategyRegistry.
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
    def default_lint_command(self) -> str:
        """Default lint command template with {file} placeholder.

        This should be a built-in linter that is commonly available
        (e.g., 'bash -n {file}', 'python -m py_compile {file}').
        """
        ...

    @property
    def extended_lint_command(self) -> str | None:
        """Optional extended lint command template with {file} placeholder.

        This is an extra tool that may or may not be installed
        (e.g., 'shellcheck {file}', 'ruff check {file}').
        Returns None if no extended linter is available.
        """
        ...

    @property
    def skip_paths(self) -> tuple[str, ...]:
        """Paths to skip (vendor, dist, node_modules, etc.)."""
        ...

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this language strategy."""
        ...
