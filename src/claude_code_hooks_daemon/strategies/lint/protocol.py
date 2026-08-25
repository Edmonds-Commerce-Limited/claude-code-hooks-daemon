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


@runtime_checkable
class NarrowsByPath(Protocol):
    """Optional capability: a strategy that does not want every file it matches.

    The registry maps a file to a strategy by extension suffix alone, which is
    the right answer for a language that OWNS its extension — a ``.py`` file is
    Python. It is the wrong answer for YAML, where the same extension covers
    CI workflows, this daemon's own config, inventories and Compose files as
    well as Ansible playbooks. Claiming all of them would report failures the
    author cannot act on, which is how a handler earns itself a
    ``enabled: false``.

    Deliberately SEPARATE from :class:`LintStrategy` rather than added to it
    (Interface Segregation, and Plan 00268 DESIGN §2): eight strategies have no
    use for this, and because ``LintStrategy`` is ``runtime_checkable`` — where
    ``isinstance`` tests member PRESENCE — folding it in would break every
    existing ``isinstance(strategy, LintStrategy)`` assertion until all eight
    carried a ``return True`` stub. Mirrors ``HasClaudeMd`` in
    ``core/claude_md_injector.py``, which expresses the same "some objects can
    also do X" shape.
    """

    def handles_file(self, file_path: str) -> bool:
        """Whether this strategy really wants a file its extension matched.

        Args:
            file_path: The file the registry is about to hand over. It may not
                exist — the registry runs before the handler's existence check,
                and a Bash-predicted target may never have been written — so an
                implementation must decide from the path alone in that case.

        Returns:
            True to accept the file, False to leave it unlinted.
        """
        ...
