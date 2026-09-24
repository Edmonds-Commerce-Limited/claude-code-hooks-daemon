"""Segment-bounded, project-relative directory/pattern matching.

The one implementation every skip-list and directory-classification site
shares (Plan 00458). Two failures, compounded, motivated this module:

1. **Bare substring, not segment.** ``skip_dir in file_path`` is a plain
   string-containment test, so ``"venv/" in file_path`` is also true for
   ``"myvenv/"`` or ``"worktree-issue-53-venv/"`` -- both first-party
   directories that merely END in a vendor/build/venv name. The guard fails
   OPEN, silently: no decision, no advisory, no log line (00422 N20).
   ``strategies/lint/common.py``'s ``matches_skip_path`` fixed this once, by
   requiring each match to land on a ``/``-preceded (or string-start)
   boundary; this module is where that fix now lives, and every other site
   is routed onto it rather than re-deriving it (see
   ``CLAUDE/Security/AsymmetricSiblingProtection.md``).
2. **Absolute, not project-relative.** Being segment-bounded is not enough on
   its own: a segment-bounded ``venv/`` still skips every file of a project
   that happens to live under a directory named exactly ``venv`` or
   ``build``. The match must be made against the path RELATIVE to the
   project root, not the raw absolute path.

Patterns follow lint's existing convention: no leading slash, a trailing
slash for a directory (``"venv/"``, not ``"/venv/"``). A leading slash is
never required for a match to land on the project root -- ``index == 0`` in
the relative (or absolute) candidate string already means "at the start of
what we were given", which is exactly the project root when a
``project_root`` was supplied.
"""

from __future__ import annotations

import os


def _project_relative_or_none(file_path: str, project_root: str | os.PathLike[str]) -> str | None:
    """``file_path`` relative to ``project_root``, or ``None`` if it escapes it.

    ``None`` covers both "outside the project" (``..``-prefixed) and the
    degenerate ``file_path == project_root`` case (``os.path.relpath``
    returns ``"."``, which can never be a directory-segment match and would
    otherwise need special-casing at every call site).
    """
    root = str(project_root).replace("\\", "/")
    raw = file_path.replace("\\", "/")
    rel = os.path.relpath(raw, root).replace("\\", "/")
    if rel == "." or rel == ".." or rel.startswith("../"):
        return None
    return rel


def _segment_bounded_contains(candidate: str, patterns: tuple[str, ...]) -> bool:
    """Whether any ``patterns`` entry occurs in ``candidate`` at a ``/``
    boundary (string start, or immediately preceded by ``/``)."""
    for pattern in patterns:
        start = 0
        while True:
            index = candidate.find(pattern, start)
            if index == -1:
                break
            if index == 0 or candidate[index - 1] == "/":
                return True
            start = index + 1
    return False


def matches_path_segment(
    file_path: str,
    patterns: tuple[str, ...],
    *,
    project_root: str | os.PathLike[str] | None = None,
) -> bool:
    """Whether ``file_path`` matches any ``patterns`` entry, segment-bounded.

    Args:
        file_path: Absolute or relative path to check.
        patterns: Directory/pattern names to match, e.g. ``("venv/", "vendor/")``.
            No leading slash; a trailing slash for a directory pattern (see
            module docstring).
        project_root: When given, ``file_path`` is first resolved RELATIVE to
            it before matching -- the fix for failure (2) above. ``None``
            (the default) matches directly against ``file_path`` as given,
            which is lint's original, still-supported behaviour for callers
            that have no project root to resolve against (a bare unit test,
            or a caller not yet migrated).

            A ``file_path`` that resolves OUTSIDE ``project_root`` (or equals
            it) is a candidate with no relative form, and the decision on
            that case belongs to the CALLER's own guard, not to this
            function: a BLOCKING guard must guard by default (fail closed) --
            skipping would fail open (00422 N20's actual lesson) -- and
            returns ``False`` (not skipped) precisely because it means
            "outside the project" is indistinguishable here from "did not
            match any pattern". A caller with a different obligation (e.g. a
            positive classification, not a skip) makes the equivalent call
            explicitly rather than this function guessing on its behalf.

    Returns:
        True if any pattern lands on a path-segment boundary in the
        (possibly relativised) candidate.
    """
    candidate = file_path.replace("\\", "/")
    if project_root is not None:
        relative = _project_relative_or_none(candidate, project_root)
        if relative is None:
            return False
        candidate = relative
    return _segment_bounded_contains(candidate, patterns)
