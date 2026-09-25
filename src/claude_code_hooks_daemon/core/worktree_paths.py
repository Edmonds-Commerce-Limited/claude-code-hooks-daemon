"""Worktree-aware path classification helpers.

When the daemon serves a hook for a file living inside a git worktree, the
file's absolute path is nested under the main project root (worktrees live at
``<root>/.claude/worktrees/<name>/`` or ``<root>/untracked/worktrees/<name>/``).
Path-classifying handlers (e.g. markdown organisation) relativise the path to
the project root and apply allowed/blocked-path rules against it. Without
worktree awareness that yields ``.claude/worktrees/<name>/CLAUDE/foo.md``,
which fails rules that expect ``CLAUDE/foo.md``.

This module is the single source of truth for worktree detection and provides
a helper that re-roots an absolute path to its nearest enclosing worktree root
so that classification matches what the user sees inside the worktree.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.utils.realpath import realpath

# Single source of truth for worktree subtree locations. The
# worktree_file_copy handler reuses this tuple.
WORKTREE_DIR_PATTERNS: tuple[str, ...] = (
    "untracked/worktrees/",
    ".claude/worktrees/",
)


def _worktree_subpath_start(relative_parts: tuple[str, ...]) -> int | None:
    """Return the component index where the in-worktree path begins.

    ``relative_parts`` is the file path relative to the project root, split into
    components. If it begins with a worktree marker (``.claude/worktrees`` or
    ``untracked/worktrees``) followed by a worktree-name component, return the
    index where the in-worktree path begins. Otherwise return ``None``.
    """
    for pattern in WORKTREE_DIR_PATTERNS:
        marker = pattern.rstrip("/").split("/")
        marker_len = len(marker)
        # Need the marker components PLUS at least a worktree-name component.
        if len(relative_parts) <= marker_len:
            continue
        if list(relative_parts[:marker_len]) == marker:
            # relative_parts[marker_len] is the worktree name; the in-worktree
            # path starts immediately after it.
            return marker_len + 1
    return None


def enclosing_checkout(abs_path: str, project_root: Path) -> tuple[Path, Path] | None:
    """The checkout ``abs_path`` belongs to, and the path relative to it.

    Returns ``(checkout_root, relative_path)``: the worktree root when
    ``abs_path`` lives inside a worktree subtree under ``project_root``, else
    ``project_root`` itself. Both are resolved. A handler that prints a remedy
    command needs the ROOT as well as the relative path, so the command it names
    acts on the checkout the file is in rather than on the main one.

    Returns ``None`` when ``abs_path`` is not inside ``project_root`` at all, or
    when it is a worktree marker path with no in-worktree subpath.
    """
    absolute = Path(realpath(abs_path))
    root = project_root.resolve()
    if not absolute.is_relative_to(root):
        # Path is outside the project entirely — not a classification target.
        return None
    relative = absolute.relative_to(root)

    parts = relative.parts
    subpath_start = _worktree_subpath_start(parts)
    if subpath_start is None:
        return root, relative

    in_worktree_parts = parts[subpath_start:]
    if not in_worktree_parts:
        return None
    return root.joinpath(*parts[:subpath_start]), Path(*in_worktree_parts)


def effective_project_relative_path(abs_path: str, project_root: Path) -> str | None:
    """Classify ``abs_path`` relative to the nearest enclosing root.

    If ``abs_path`` lives inside a worktree subtree under ``project_root``, the
    returned path is relative to the WORKTREE root (e.g.
    ``CLAUDE/LLM-UPDATE.md``). Otherwise it is relative to ``project_root``.

    Returns ``None`` when ``abs_path`` is not inside ``project_root`` at all, or
    when it is a worktree marker path with no in-worktree subpath.
    """
    located = enclosing_checkout(abs_path, project_root)
    if located is None:
        return None
    return str(located[1])
