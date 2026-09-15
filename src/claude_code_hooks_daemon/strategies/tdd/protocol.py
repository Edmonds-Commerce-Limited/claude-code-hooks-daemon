"""TDD Strategy Protocol - interface for language-specific TDD enforcement."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TddStrategy(Protocol):
    """Strategy interface for language-specific TDD enforcement.

    Each implementation encapsulates ALL language-specific logic for:
    - Identifying test files by naming convention
    - Identifying production source directories
    - Identifying directories to skip (vendor, build, etc.)
    - Computing expected test filenames from source filenames

    To add a new language: implement this Protocol and register in TddStrategyRegistry.
    """

    @property
    def language_name(self) -> str:
        """Human-readable language name for error messages."""
        ...

    @property
    def extensions(self) -> tuple[str, ...]:
        """File extensions handled by this strategy (e.g., ('.py',))."""
        ...

    def is_test_file(self, file_path: str) -> bool:
        """Check if a file is a test file for this language.

        Should check BOTH:
        - Common test directories (via common.is_in_common_test_directory)
        - Language-specific filename patterns (e.g., test_*.py, *.test.js)
        """
        ...

    def is_production_source(self, file_path: str) -> bool:
        """Check if a file is in a production source directory.

        Each language has its own conventions for source directories.
        Should also exclude language-specific init files (e.g., Python's __init__.py)
        — delegate that half to :meth:`is_excluded_source_file` rather than
        re-testing it here, so the two cannot disagree.
        """
        ...

    def is_excluded_source_file(self, file_path: str) -> bool:
        """Whether this language NEVER treats ``file_path`` as production source.

        A file-level veto, independent of LOCATION: Python's ``__init__.py``
        is a package marker wherever it sits. This is deliberately separate
        from :meth:`is_production_source`, which answers the directory
        question as well — the handler needs the two apart (Plan 00419 N6).

        A project that DECLARES ``layout.source_dirs`` has the handler consult
        the declared layout FIRST, because a project stating where its source
        lives outranks per-language inference. But that answers "is this file
        in a source DIRECTORY?", and if it is allowed to stand alone it
        silently switches off every exclusion bundled inside
        ``is_production_source``. Declaring your layout must not cost you
        Python's ``__init__.py`` exemption.

        Most languages have no such file and return False.
        """
        ...

    def should_skip(self, file_path: str, content: str = "") -> bool:
        """Check if a file should be skipped (vendor, build dirs, interfaces, etc.).

        Args:
            file_path: Path to the file being written.
            content: Optional file content for content-based detection
                (e.g., PHP interface declarations).
        """
        ...

    def compute_test_filename(self, source_filename: str) -> str:
        """Compute expected test filename from source filename.

        E.g., 'module.py' -> 'test_module.py' (Python)
              'server.go' -> 'server_test.go' (Go)
              'helpers.ts' -> 'helpers.test.ts' (JS/TS)
        """
        ...

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this language strategy."""
        ...
