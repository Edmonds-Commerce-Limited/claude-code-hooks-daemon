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

    Segment-bounded against the path relative to the project root (Plan
    00458 follow-up): a leading slash is stripped from each pattern rather
    than enforced, because a leading slash would never land at the start of
    a project-relative path's first segment -- exactly the fix already
    applied to :func:`is_in_common_test_directory` and to the shared skip-
    list sites, extended here to every per-language TDD strategy's
    ``_SOURCE_DIRECTORIES``/``_SKIP_DIRECTORIES`` (11 languages share this
    one function). Without ``project_root``, a project living under an
    ancestor directory sharing a pattern's name (``/srv/vendor/app/``,
    ``/home/u/build/proj/``) had every file inside it misclassified as
    vendored/skip or as already-a-source-directory -- the absolute path
    contained the pattern even though the pattern never appears relative to
    the project.
    """
    patterns = tuple(f"{directory.lstrip('/').rstrip('/')}/" for directory in directories)
    return matches_path_segment(file_path, patterns, project_root=resolve_project_root())
