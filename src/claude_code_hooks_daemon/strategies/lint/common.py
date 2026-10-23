"""Shared constants and utilities for lint strategies - DRY."""

import shutil
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.strategies.lint.protocol import ProvidesCommandValues
from claude_code_hooks_daemon.utils.path_segments import matches_path_segment

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


FILE_PLACEHOLDER = "{file}"

#: The running interpreter's own ``bin`` directory - the project venv, where a
#: Python project's console-script linters (``ruff``, ``mypy``) live.
INTERPRETER_BIN_DIR: Final[Path] = Path(sys.executable).parent


def resolve_lint_executable(executable: str, bin_dirs: tuple[Path, ...]) -> str | None:
    """Resolve a lint tool name to a runnable path, or None if absent.

    The ONE resolver both lint gates use (`lint_on_edit` at Write/Edit time,
    `staged_lint_gate` at commit time), so the two can never launch different
    binaries for the same file. When the gate skipped the sub-project's tool
    directories, a pinned ``node_modules/.bin`` copy linted the file at edit
    time and a global ``PATH`` copy re-linted it at commit.

    Search order: ``bin_dirs`` (the file's own workspace tool directories,
    e.g. ``vendor/bin``, ``node_modules/.bin``) in order, then
    :data:`INTERPRETER_BIN_DIR`, then ``PATH``. The workspace comes first
    because a project pins its linter version in its own manifest
    (Plan 00296). An absolute ``executable`` is returned unchanged.

    Returning None rather than guessing is deliberate: callers treat an absent
    tool as "not checked", never as a failure, because a tool that is not
    installed must never block anyone.

    Args:
        executable: The command's first element, bare or absolute.
        bin_dirs: The file's resolved workspace ``bin_dirs``.

    Returns:
        The absolute path to run, or None when the tool is not found.
    """
    if Path(executable).is_absolute():
        return executable
    for directory in (*bin_dirs, INTERPRETER_BIN_DIR):
        candidate = directory / executable
        # eacces-safe-exempt: resolving the LINTER binary from configured tool
        # directories, not the file under lint.
        if candidate.is_file():
            return str(candidate)
    return shutil.which(executable)


def build_lint_argv(
    template: str,
    file_path: str,
    strategy: object,
    *,
    effective_path: str | None = None,
) -> list[str]:
    """Turn a lint command template into an argv list. The ONE place this is done.

    The template is split on whitespace FIRST and each placeholder is then
    replaced only where it is a whole element, so a substituted value is always
    exactly one argument: a path with a space is not re-tokenised, and a path or
    manifest value carrying a flag cannot append that flag to the linter's own
    command line (Plan 00412 class 7). Substituting into the string and
    splitting afterwards would do both.

    ``{file}`` becomes ``effective_path`` (default ``file_path``; Go lints the
    package directory rather than the file). A strategy implementing
    :class:`ProvidesCommandValues` also fills its own placeholders (Rust's
    ``{edition}``), so every caller that runs a strategy template gets them
    filled. A template that does not mention a placeholder is unaffected.
    """
    placeholders = {FILE_PLACEHOLDER: effective_path if effective_path is not None else file_path}
    if isinstance(strategy, ProvidesCommandValues):
        placeholders.update(
            {f"{{{name}}}": value for name, value in strategy.command_values(file_path).items()}
        )
    return [placeholders.get(part, part) for part in template.split()]


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

    A thin re-export of :func:`~claude_code_hooks_daemon.utils.path_segments.
    matches_path_segment` (Plan 00458), which now holds the one
    implementation every skip-list site shares -- this function's own
    docstring is where the segment-vs-substring fix was first written, and
    every other site was moved onto it rather than re-deriving it (see
    ``CLAUDE/Security/AsymmetricSiblingProtection.md``). Kept under this name
    because lint/ESLint strategies import it by this name; no
    ``project_root`` is passed here, so behaviour is unchanged: segment-
    bounded directly against ``file_path`` as given.

    Args:
        file_path: Full file path to check.
        skip_paths: Tuple of path patterns to skip.

    Returns:
        True if the file is in a skip path.
    """
    return matches_path_segment(file_path, skip_paths)
