"""Which ignored paths a worktree removal may destroy, because each is rebuilt on demand.

The list is ``branches.cleanup_after_merge.regenerable`` (Plan 00558 Task 3.1).
Entries are the ``git ls-files --others --ignored --directory`` form: relative to
the worktree root, a directory ending in ``/``.

Pattern dialect, a gitignore-style subset:

- A trailing ``/`` matches directories only (and so everything inside one).
- A pattern with no other ``/`` is a NAME: it matches a path segment at any depth.
- A pattern with a ``/`` (a leading one included) is anchored to the root, and
  each ``/``-separated segment is matched against one path segment.
- ``*`` and ``?`` never cross a ``/``.

:data:`NEVER_REGENERABLE` holds an agent's working notes, so no list may cover
it; the config load rejects one that does.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence

#: The model default for ``branches.cleanup_after_merge.regenerable``.
DEFAULT_REGENERABLE_STORES: tuple[str, ...] = (
    "untracked/venv-*/",
    "untracked/qa/",
    "untracked/docs-qa/",
    "untracked/branch-inventory/",
    "untracked/daemon-*",
    "untracked/events-*",
    "untracked/.venv-bootstrap*",
    "untracked/lsp-venv/",
    ".claude/hooks-daemon/",
    "*.egg-info/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
)

#: The scratch notes directory: always a blocker, whatever a project lists.
NEVER_REGENERABLE = "untracked/scratch/"

#: Entries checked to prove a pattern list leaves the scratch directory alone.
_NEVER_REGENERABLE_PROBES = (NEVER_REGENERABLE, f"{NEVER_REGENERABLE}notes.md")


def _matches(entry_parts: Sequence[str], entry_is_dir: bool, pattern: str) -> bool:
    """Whether ``pattern`` matches the entry or any directory above it."""
    dir_only = pattern.endswith("/")
    body = pattern.strip("/")
    anchored = pattern.startswith("/") or "/" in body
    segments = body.split("/")
    for depth in range(1, len(entry_parts) + 1):
        is_dir = depth < len(entry_parts) or entry_is_dir
        if dir_only and not is_dir:
            continue
        if anchored:
            if depth == len(segments) and all(
                fnmatch.fnmatchcase(part, segment)
                for part, segment in zip(entry_parts[:depth], segments, strict=True)
            ):
                return True
        elif fnmatch.fnmatchcase(entry_parts[depth - 1], body):
            return True
    return False


def is_regenerable(entry: str, patterns: Sequence[str]) -> bool:
    """Whether an ignored ``ls-files --directory`` entry lies under one of ``patterns``."""
    parts = entry.strip("/").split("/")
    return any(_matches(parts, entry.endswith("/"), pattern) for pattern in patterns)


def never_regenerable_violations(patterns: Sequence[str]) -> list[str]:
    """The patterns that would class :data:`NEVER_REGENERABLE` as regenerable."""
    return [
        pattern
        for pattern in patterns
        if any(is_regenerable(probe, [pattern]) for probe in _NEVER_REGENERABLE_PROBES)
    ]


__all__ = [
    "DEFAULT_REGENERABLE_STORES",
    "NEVER_REGENERABLE",
    "is_regenerable",
    "never_regenerable_violations",
]
