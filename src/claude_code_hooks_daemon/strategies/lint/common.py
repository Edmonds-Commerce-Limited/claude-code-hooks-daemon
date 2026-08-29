"""Shared constants and utilities for lint strategies - DRY."""

from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES

# Lint's own domain extras (Plan 00288 Task 3.2, measurement doc §3): a byte-
# compiled cache and VCS internals, neither of which is "vendored/build" but
# both harmless to skip when linting.
_LINT_EXTRA_SKIP_PATH_NAMES: tuple[str, ...] = ("__pycache__", ".git")

# Common paths to skip across ALL languages (vendor, build, etc.) -- the
# canonical core plus lint's own extras, each slash-suffixed so a skip
# pattern never matches a FILE sharing the bare name (see
# ``matches_skip_path``).
COMMON_SKIP_PATHS: tuple[str, ...] = tuple(
    f"{name}/" for name in (*sorted(CORE_VENDORED_BUILD_DIR_NAMES), *_LINT_EXTRA_SKIP_PATH_NAMES)
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
