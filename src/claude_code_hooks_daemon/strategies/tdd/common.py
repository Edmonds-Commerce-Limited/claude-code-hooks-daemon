"""Shared constants and utilities for TDD strategies - DRY."""

from claude_code_hooks_daemon.utils.path_exclusion import resolve_project_root
from claude_code_hooks_daemon.utils.path_segments import matches_path_segment

# Common test directory names recognized across ALL languages. No leading
# slash (Plan 00458): matched project-relative, and a leading slash would
# never land at the start of a relative path's first segment.
COMMON_TEST_DIRECTORIES: tuple[str, ...] = (
    "tests/",
    "test/",
    "__tests__/",
    "spec/",
)


def is_in_common_test_directory(file_path: str) -> bool:
    """Check if file is in a common test directory (language-agnostic).

    Segment-bounded against the path relative to the project root (Plan
    00458): a bare substring test would also match e.g. a project living
    under a directory literally named "test", misclassifying every one of
    its files as already-a-test.
    """
    return matches_path_segment(
        file_path, COMMON_TEST_DIRECTORIES, project_root=resolve_project_root()
    )


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
