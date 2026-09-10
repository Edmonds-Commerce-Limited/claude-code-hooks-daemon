"""LSP-noise Strategy Protocol - interface for per-language LSP exclude checks."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.relevance import RelevanceContext


@runtime_checkable
class LspNoiseStrategy(Protocol):
    """Strategy interface for one language's LSP-noise checks.

    Each implementation encapsulates ALL language-specific knowledge of:
    - The toolchain marker that makes this language relevant to a project
    - The language server process name(s) a staleness check matches against
    - How that language's tooling learns which trees are not project code
      (a config file's ``exclude`` key, workspace/module membership, or -
      when the tool takes no project-level exclude at all - the exact
      client-settings fix to print)

    To add a new language: implement this Protocol and register it in
    LspNoiseStrategyRegistry.
    """

    @property
    def language_name(self) -> str:
        """Human-readable language name for advisory messages."""
        ...

    @property
    def process_names(self) -> tuple[str, ...]:
        """Language-server process name(s) matched against a live process's argv."""
        ...

    def is_relevant(self, context: RelevanceContext) -> bool:
        """Whether this language's toolchain marker is present in the project."""
        ...

    def exclude_finding(
        self, root: Path, required: frozenset[str]
    ) -> tuple[list[str], Path | None]:
        """This language's exclude-noise finding for the given project root.

        Args:
            root: The project root to check.
            required: Every tree (project-root-relative) the daemon knows is
                not project code - the daemon-derived set every strategy
                checks against, never a language-specific list.

        Returns:
            A tuple of (advisory lines, config path). The advisory lines are
            empty when this language's exclude coverage is complete. The
            config path is the file whose mtime anchors the companion
            staleness check (R-LSP-SERVER-STALE) - None when no such file
            exists yet, which correctly disables staleness (nothing to have
            gone stale against).
        """
        ...

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this language's LSP-noise strategy."""
        ...
