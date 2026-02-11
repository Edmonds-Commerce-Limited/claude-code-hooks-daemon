"""Shared constants and utilities for TDD strategies - DRY."""

# Common test directory names recognized across ALL languages
COMMON_TEST_DIRECTORIES: tuple[str, ...] = (
    "/tests/",
    "/test/",
    "/__tests__/",
    "/spec/",
)


def is_in_common_test_directory(file_path: str) -> bool:
    """Check if file is in a common test directory (language-agnostic)."""
    return any(test_dir in file_path for test_dir in COMMON_TEST_DIRECTORIES)


def matches_directory(file_path: str, directories: tuple[str, ...]) -> bool:
    """Check if file path matches any directory pattern.

    Handles normalization: ensures patterns have leading / and trailing /.
    """
    for directory in directories:
        pattern = directory if directory.startswith("/") else f"/{directory}"
        if not pattern.endswith("/"):
            pattern += "/"
        if pattern in file_path:
            return True
    return False
