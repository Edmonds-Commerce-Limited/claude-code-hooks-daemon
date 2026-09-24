"""Shared utilities for security strategy implementations."""

from claude_code_hooks_daemon.utils.path_exclusion import resolve_project_root
from claude_code_hooks_daemon.utils.path_segments import matches_path_segment

# Directories to skip (vendor code, test fixtures, documentation, rule
# definitions). No leading slash (Plan 00458): matched project-relative, and
# a leading slash would never land at the start of a relative path's first
# segment. ".env.example" is a bare filename, not a directory, and is
# unaffected by that convention.
SKIP_PATTERNS: tuple[str, ...] = (
    "vendor/",
    "node_modules/",
    "tests/fixtures/",
    "tests/assets/",
    ".env.example",
    "docs/",
    "CLAUDE/",
    "eslint-rules/",
    "tests/PHPStan/",
    "strategies/security/",
)

# Sentinel extension for universal strategies (apply to all file types)
UNIVERSAL_EXTENSION = "*"


def should_skip(file_path: str) -> bool:
    """Check if file should be excluded from security scanning.

    Segment-bounded against the path relative to the project root (Plan
    00458 / 00422 N20): a bare substring test also matched a worktree merely
    named "...-venv/" or a project whose directory happened to share a
    vendor/build name's letters, silently standing this guard down.
    """
    return matches_path_segment(file_path, SKIP_PATTERNS, project_root=resolve_project_root())
