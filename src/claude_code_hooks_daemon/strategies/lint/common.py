"""Shared constants and utilities for lint strategies - DRY."""

# Common paths to skip across ALL languages (vendor, build, etc.)
COMMON_SKIP_PATHS: tuple[str, ...] = (
    "node_modules/",
    "dist/",
    "vendor/",
    ".build/",
    "coverage/",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".git/",
    "target/",
    "build/",
)


def matches_skip_path(file_path: str, skip_paths: tuple[str, ...]) -> bool:
    """Check if file path matches any skip path pattern.

    Args:
        file_path: Full file path to check.
        skip_paths: Tuple of path patterns to skip.

    Returns:
        True if the file is in a skip path.
    """
    return any(skip in file_path for skip in skip_paths)
