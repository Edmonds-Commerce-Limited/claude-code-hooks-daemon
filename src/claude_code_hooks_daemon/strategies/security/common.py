"""Shared utilities for security strategy implementations."""

# Directories to skip (vendor code, test fixtures, documentation, rule definitions)
SKIP_PATTERNS: tuple[str, ...] = (
    "/vendor/",
    "/node_modules/",
    "/tests/fixtures/",
    "/tests/assets/",
    ".env.example",
    "/docs/",
    "/CLAUDE/",
    "/eslint-rules/",
    "/tests/PHPStan/",
    "/strategies/security/",
)

# Sentinel extension for universal strategies (apply to all file types)
UNIVERSAL_EXTENSION = "*"


def should_skip(file_path: str) -> bool:
    """Check if file should be excluded from security scanning."""
    return any(skip in file_path for skip in SKIP_PATTERNS)
