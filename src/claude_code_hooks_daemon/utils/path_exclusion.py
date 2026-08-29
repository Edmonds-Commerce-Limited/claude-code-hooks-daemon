"""Shared glob-based path exclusion for content-scanning blocking handlers.

Client projects — especially QA/linting libraries whose job is to contain
deliberately-"bad" code samples — need to exempt paths from the content
blockers (`security_antipattern`, `qa_suppression`, `error_hiding_blocker`).
This module provides one glob matcher those handlers share, so exclusion
behaves identically everywhere.

Glob semantics are a pragmatic gitignore-style subset (stdlib-only, no runtime
dependency):

- ``*``  matches any run of characters within a single path segment.
- ``?``  matches exactly one character within a single path segment.
- ``**`` matches any number of path segments (including zero), e.g.
  ``samples/**/*.py`` matches both ``samples/x.py`` and ``samples/a/b/x.py``.
- A leading ``/`` anchors the pattern to the project root; without it the
  pattern may match at any directory depth.

Patterns are matched against the project-relative path (when ``project_root``
is given and the file lives under it) and against the raw path, so a handler
may pass either an absolute or a relative ``file_path``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

# Compiled-pattern cache: the same handful of client globs are matched on every
# Write/Edit, so translating + compiling once per pattern is worth it.
_REGEX_CACHE: dict[str, re.Pattern[str]] = {}


def _glob_to_regex(pattern: str) -> str:
    """Translate a gitignore-style glob into a full-match regex string.

    A leading ``/`` anchors to the (relative) path start; otherwise a
    ``(?:.*/)?`` prefix lets the pattern match at any directory depth.
    """
    anchored = pattern.startswith("/")
    body = pattern[1:] if anchored else pattern

    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        char = body[i]
        if char == "*":
            if i + 1 < n and body[i + 1] == "*":
                # '**' — any number of path segments.
                i += 2
                if i < n and body[i] == "/":
                    # '**/' consumes the slash so it can match zero segments.
                    i += 1
                    out.append("(?:[^/]+/)*")
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "/":
            out.append("/")
        else:
            out.append(re.escape(char))
        i += 1

    regex = "".join(out)
    if not anchored:
        regex = "(?:.*/)?" + regex
    return regex


def _compiled(pattern: str) -> re.Pattern[str]:
    """Return the cached compiled full-match regex for ``pattern``."""
    compiled = _REGEX_CACHE.get(pattern)
    if compiled is None:
        compiled = re.compile(_glob_to_regex(pattern))
        _REGEX_CACHE[pattern] = compiled
    return compiled


def _candidate_paths(file_path: str, project_root: str | os.PathLike[str] | None) -> list[str]:
    """Return the path strings a pattern is matched against.

    Always includes the raw path with any leading slash stripped; also includes
    the project-relative path when ``project_root`` is given and the file lives
    under it (so leading-``/`` anchored patterns resolve against the root).
    """
    raw = file_path.replace("\\", "/")
    candidates = [raw.lstrip("/")]
    if project_root is not None:
        root = str(project_root).replace("\\", "/")
        rel = os.path.relpath(raw, root).replace("\\", "/")
        if rel != ".." and not rel.startswith("../"):
            candidates.insert(0, rel)
    return candidates


def merge_exclude_patterns(*groups: Sequence[str] | None) -> list[str]:
    """Union the given pattern groups into one ordered, de-duplicated list.

    Exclusion is additive: a handler's effective excludes are the union of its
    built-in defaults, the project-level ``daemon.exclude_paths`` default, and
    its own per-handler ``exclude_paths`` option — none overrides the others.
    Empty/None groups and empty patterns are skipped; first-seen order is kept.
    """
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not group:
            continue
        for pattern in group:
            if pattern and pattern not in seen:
                seen.add(pattern)
                merged.append(pattern)
    return merged


def resolve_project_root() -> str | None:
    """Best-effort absolute project root for anchored-glob matching.

    Returns None when ProjectContext is not initialised (e.g. unit tests), in
    which case only unanchored patterns match (against the raw path). Imported
    lazily to avoid a util→core import cycle at module load.
    """
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    if not getattr(ProjectContext, "_initialized", False):
        return None
    return str(ProjectContext.project_root())


def path_matches_globs(
    file_path: str,
    patterns: Sequence[str] | None,
    *,
    project_root: str | os.PathLike[str] | None = None,
) -> bool:
    """Return True if ``file_path`` matches any glob in ``patterns``.

    The glob dialect is this module's, documented at the top. Exclusion is only
    the most common *use* of the answer, not the answer itself — a project may
    also want to select paths in order to treat them SPECIALLY rather than to
    skip them, which is what ``tdd_enforcement``'s ``test_path_map`` does
    (Plan 00251). Sharing this matcher keeps one glob dialect across the whole
    config surface, so a project learns the syntax once.

    Args:
        file_path: Absolute or relative path being considered.
        patterns: Glob patterns. ``None`` or empty never matches.
        project_root: Optional project root; enables project-relative and
            leading-``/`` anchored matching.

    Returns:
        True if any pattern matches any candidate form of the path.
    """
    if not patterns:
        return False
    candidates = _candidate_paths(file_path, project_root)
    for pattern in patterns:
        if not pattern:
            continue
        compiled = _compiled(pattern)
        if any(compiled.fullmatch(candidate) for candidate in candidates):
            return True
    return False


def is_path_excluded(
    file_path: str,
    patterns: Sequence[str] | None,
    *,
    project_root: str | os.PathLike[str] | None = None,
) -> bool:
    """Return True if ``file_path`` matches any exclusion glob in ``patterns``.

    A thin naming layer over :func:`path_matches_globs`: identical behaviour,
    but the name states what the caller MEANS by a match. Kept as the entry point
    for the exclusion callers so their code reads as exclusion rather than as
    pattern-matching.

    Args:
        file_path: Absolute or relative path of the file being written/edited.
        patterns: Glob patterns to exclude. ``None`` or empty never excludes.
        project_root: Optional project root; enables project-relative and
            leading-``/`` anchored matching.

    Returns:
        True if any pattern matches any candidate form of the path.
    """
    return path_matches_globs(file_path, patterns, project_root=project_root)


def handler_excludes_path(
    file_path: str,
    *,
    handler_patterns: Sequence[str] | None,
    project_patterns: Sequence[str] | None,
    defaults: Sequence[str] | None = None,
) -> bool:
    """Whether a handler should skip ``file_path`` given all three exclude sources.

    This is the handler-facing decision, defined ONCE. It was previously copied
    into several handlers as a private ``_is_excluded`` — byte-identical in most,
    with ``error_hiding_blocker`` differing only by prepending its own defaults
    and dropping the short-circuit — which is what turned "paste another copy"
    into "extract the one that exists" (Plan 00251). The exact number of
    current callers is deliberately NOT stated here: it drifts every time a
    handler adopts this function without this docstring being updated in the
    same change (Plan 00288 DESIGN §1c). Grep for callers of
    ``handler_excludes_path`` for the current count.

    The three sources are ADDITIVE and none overrides another: built-in
    ``defaults``, the project-wide ``daemon.exclude_paths``, and the handler's own
    ``exclude_paths`` option.

    Args:
        file_path: Path of the file being written or edited.
        handler_patterns: The handler's own ``exclude_paths`` option.
        project_patterns: Project-wide ``daemon.exclude_paths``, injected by the
            registry after construction.
        defaults: The handler's built-in exclusions, if it has any.

    Returns:
        True when any source matches, so the handler should not act on this path.
    """
    patterns = merge_exclude_patterns(defaults, project_patterns, handler_patterns)
    # Short-circuit on "nothing configured anywhere". `is_path_excluded` would
    # also return False, but only after `resolve_project_root()` has imported
    # ProjectContext — pointless work on the common path where no project
    # configures exclusions.
    if not patterns:
        return False
    return is_path_excluded(file_path, patterns, project_root=resolve_project_root())
