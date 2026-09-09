"""Shared constants and utilities for lint strategies - DRY."""

import tempfile
from functools import lru_cache

from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES

#: Prefix for the per-process compiler-output directory, so a leftover is
#: attributable to this daemon when someone goes looking in the temp dir.
_LINT_OUTPUT_DIR_PREFIX = "claude-hooks-daemon-lint-"

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


@lru_cache(maxsize=1)
def lint_output_dir() -> str:
    """One directory for every artefact a lint command is told to emit.

    A syntax check that compiles has to put its output somewhere, and beside
    the user's source file is the one place it must not go. Kotlin (``-d``)
    and Rust (``--out-dir``) each named a FIXED path in the shared temp
    directory, which hands two problems to a multi-user host: the name is
    predictable, so another user can pre-create it as a symlink and steer
    compiler output through it, and two concurrent lint runs write into the
    same place regardless of who owns it.

    ``mkdtemp`` answers both -- an unguessable name, created 0700, once per
    process -- and being resolved here rather than spelled in each strategy
    means a third caller cannot reintroduce a literal.

    Not cleaned up on exit: the artefacts are small, the daemon is long-lived,
    and a strategy that deleted the directory mid-process would break the next
    lint run in the same process.

    Returns:
        Absolute path to the shared per-process output directory.
    """
    return tempfile.mkdtemp(prefix=_LINT_OUTPUT_DIR_PREFIX)


def matches_skip_path(file_path: str, skip_paths: tuple[str, ...]) -> bool:
    """Check if file path matches any skip path pattern, segment-bounded.

    Each ``skip`` pattern (e.g. ``"build/"``) must land on a path-segment
    boundary in ``file_path``: at the start of the string, or immediately
    preceded by ``/``. A bare substring test would also match ``"build/"``
    inside ``"rebuild/"`` or ``"venv/"`` inside ``"myvenv/"`` -- both
    first-party directories that merely end with the same letters as a
    vendor/build directory -- which would wrongly skip lint/ESLint checks
    on real source files (fail-open).

    Args:
        file_path: Full file path to check.
        skip_paths: Tuple of path patterns to skip.

    Returns:
        True if the file is in a skip path.
    """
    for skip in skip_paths:
        start = 0
        while True:
            index = file_path.find(skip, start)
            if index == -1:
                break
            if index == 0 or file_path[index - 1] == "/":
                return True
            start = index + 1
    return False
