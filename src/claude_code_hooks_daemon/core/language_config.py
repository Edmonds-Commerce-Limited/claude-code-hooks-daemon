"""Language-specific configuration for multi-language handler support."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageConfig:
    """Configuration for language-specific handler behavior.

    This dataclass encapsulates all language-specific settings needed by
    generic handler base classes (QaSuppressionBlockerBase, TddEnforcementBase).

    Attributes:
        name: Human-readable language name (e.g., "Python", "Go")
        extensions: File extensions for this language (e.g., (".py",))
        qa_forbidden_patterns: Regex patterns for QA suppression comments to block
        test_file_pattern: Pattern for test file naming convention
            - {filename} = full filename including extension
            - {basename} = filename without extension
        qa_tool_names: Names of QA tools for this language (for error messages)
        qa_tool_docs_urls: Documentation URLs for QA tools
        skip_directories: Directories to skip when checking files
    """

    name: str
    extensions: tuple[str, ...]
    qa_forbidden_patterns: tuple[str, ...]
    test_file_pattern: str
    qa_tool_names: tuple[str, ...]
    qa_tool_docs_urls: tuple[str, ...]
    skip_directories: tuple[str, ...]


# Python language configuration
PYTHON_CONFIG = LanguageConfig(
    name="Python",
    extensions=(".py",),
    qa_forbidden_patterns=(
        r"#\s*type:\s*ignore",  # MyPy
        r"#\s*noqa",  # Ruff/Flake8
        r"#\s*pylint:\s*disable",  # Pylint
        r"#\s*pyright:\s*ignore",  # Pyright
        r"#\s*mypy:\s*ignore-errors",  # MyPy module-level
    ),
    test_file_pattern="test_{filename}",
    qa_tool_names=("MyPy", "Ruff", "Pylint", "Pyright"),
    qa_tool_docs_urls=(
        "https://mypy.readthedocs.io/",
        "https://docs.astral.sh/ruff/",
        "https://pylint.readthedocs.io/",
    ),
    skip_directories=(
        "tests/fixtures/",
        "migrations/",
        "vendor/",
        ".venv/",
        "venv/",
    ),
)

# Go language configuration
GO_CONFIG = LanguageConfig(
    name="Go",
    extensions=(".go",),
    qa_forbidden_patterns=(
        r"//\s*nolint",  # golangci-lint
        r"//\s*lint:ignore",  # golint
    ),
    test_file_pattern="{basename}_test.go",
    qa_tool_names=("golangci-lint", "golint"),
    qa_tool_docs_urls=(
        "https://golangci-lint.run/",
        "https://go.dev/doc/effective_go",
        "https://github.com/golang/go/wiki/CodeReviewComments",
    ),
    skip_directories=(
        "vendor/",
        "testdata/",
    ),
)

# PHP language configuration
PHP_CONFIG = LanguageConfig(
    name="PHP",
    extensions=(".php",),
    qa_forbidden_patterns=(
        r"@phpstan-ignore-next-line",  # PHPStan
        r"@psalm-suppress",  # Psalm
        r"phpcs:ignore",  # PHP_CodeSniffer
        r"@codingStandardsIgnoreLine",  # PHPCS
        r"@phpstan-ignore-line",  # PHPStan alternative
    ),
    test_file_pattern="{basename}Test.php",
    qa_tool_names=("PHPStan", "Psalm", "PHP_CodeSniffer"),
    qa_tool_docs_urls=(
        "https://phpstan.org/",
        "https://psalm.dev/",
        "https://github.com/squizlabs/PHP_CodeSniffer",
    ),
    skip_directories=(
        "tests/fixtures/",
        "vendor/",
    ),
)

# Language registry mapping extensions to configs
_LANGUAGE_REGISTRY: dict[str, LanguageConfig] = {}

# Register all language configs
for config in [PYTHON_CONFIG, GO_CONFIG, PHP_CONFIG]:
    for ext in config.extensions:
        _LANGUAGE_REGISTRY[ext.lower()] = config


def get_language_config(file_path: str) -> LanguageConfig | None:
    """Get language configuration for a file path.

    Args:
        file_path: Path to the file

    Returns:
        LanguageConfig for the file's language, or None if unknown
    """
    # Case-insensitive extension matching
    file_path_lower = file_path.lower()

    for ext, config in _LANGUAGE_REGISTRY.items():
        if file_path_lower.endswith(ext):
            return config

    return None
