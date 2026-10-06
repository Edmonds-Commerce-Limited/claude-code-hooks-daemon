"""The protected globs as git pathspecs, so a listing names only candidates (N355 part 3).

``git ls-files --others --ignored`` lists every ignored file: on a working copy
that keeps virtualenvs and worktrees under an ignored directory that is hundreds
of thousands of paths, which outran the index build's timeout. Almost none of
them can be protected. Giving git the protected globs as ``:(glob)`` pathspecs
makes it list only the paths a glob could select.

The narrowing is sound only as a SUPERSET of what
:func:`~claude_code_hooks_daemon.utils.path_exclusion.first_matching_glob`
selects (the Python matcher still runs on whatever git returns), because a
protected file git leaves out is a silent gap. So this module turns a pattern
into a pathspec only where the two dialects provably agree or git is broader,
and answers ``None`` (list everything) wherever they might not:

* ``[`` and ``\\`` are literal here and magic to git; a leading ``:`` is
  pathspec magic; ``**`` that is not a whole path segment is read differently.
* The matcher also tries the ABSOLUTE path, so a multi-segment pattern whose
  first segment can match a directory above the project root selects files the
  relative form never would.

One known gap, which this narrowing does not close: a symlink that is ignored
and untracked, whose own name matches no glob but whose target does, is not
listed. Tracked symlinks are, because the tracked listing is not narrowed.
"""

import fnmatch
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.vendor_paths import VENDOR_DIRS_TOKEN

#: Pathspec magic: ``*``/``?`` stay inside a segment and ``**`` spans segments, as here.
PATHSPEC_MAGIC: Final[str] = ":(glob)"

_ANY_DEPTH: Final[str] = "**"
_ANY_DEPTH_PREFIX: Final[str] = "**/"
#: Characters that mean something to git's glob but not to the matcher here.
_GIT_ONLY_SYNTAX: Final[tuple[str, ...]] = ("[", "\\")
_PATHSPEC_MAGIC_LEAD: Final[str] = ":"


def git_pathspecs(patterns: Sequence[str], project_root: Path) -> tuple[str, ...] | None:
    """Pathspecs naming every path a protected glob can select, or ``None``.

    ``None`` means no sound narrowing exists for at least one pattern, so the
    caller must list everything. An empty result means there is nothing to select.
    """
    ancestors = _root_components(project_root)
    root_prefixes = tuple(
        dict.fromkeys(
            root.replace(os.sep, "/").strip("/")
            for root in (str(project_root), os.path.realpath(project_root))
        )
    )
    specs: dict[str, None] = {}
    for pattern in patterns:
        if not pattern:
            continue
        found = _pathspecs_for(pattern, ancestors, root_prefixes)
        if found is None:
            return None
        specs.update(dict.fromkeys(found))
    return tuple(specs)


def _root_components(project_root: Path) -> tuple[str, ...]:
    """The directory names of the root, as spelled and as resolved."""
    spellings = dict.fromkeys((str(project_root), os.path.realpath(project_root)))
    return tuple(
        dict.fromkeys(part for spelling in spellings for part in spelling.split("/") if part)
    )


def _pathspecs_for(
    pattern: str, ancestors: tuple[str, ...], root_prefixes: tuple[str, ...]
) -> list[str] | None:
    if pattern == VENDOR_DIRS_TOKEN or pattern.startswith(_PATHSPEC_MAGIC_LEAD):
        return None
    if any(char in pattern for char in _GIT_ONLY_SYNTAX):
        return None
    anchored = pattern.startswith("/")
    body = pattern[1:] if anchored else pattern
    segments = body.split("/")
    if not _recursive_segments_are_whole(segments) or "" in segments[:-1]:
        return None
    if not body or segments == [""]:
        return None
    if anchored:
        for prefix in root_prefixes:
            remainder = _below(body, prefix)
            if remainder is not None:
                return _anchored_under_root(body, remainder)
    effective = _without_leading_recursion(segments)
    if not effective or effective == [_ANY_DEPTH]:
        return None
    if len(effective) > 1 and _can_start_above_root(effective[0], ancestors):
        return None
    if anchored:
        return [PATHSPEC_MAGIC + body]
    return [PATHSPEC_MAGIC + _ANY_DEPTH_PREFIX + "/".join(effective)]


def _recursive_segments_are_whole(segments: list[str]) -> bool:
    """Is every ``**`` a whole segment, as both dialects need to read it alike?"""
    return all(_ANY_DEPTH not in segment or segment == _ANY_DEPTH for segment in segments)


def _without_leading_recursion(segments: list[str]) -> list[str]:
    """``segments`` minus the leading ``**`` ones, which say what the any-depth prefix says."""
    start = 0
    while start < len(segments) - 1 and segments[start] == _ANY_DEPTH:
        start += 1
    return segments[start:]


def _below(body: str, prefix: str) -> str | None:
    """``body`` with the literal ``prefix/`` removed, or None when it does not start with it."""
    lead = prefix + "/"
    if prefix and body.startswith(lead):
        return body[len(lead) :]
    return None


def _anchored_under_root(body: str, remainder: str) -> list[str] | None:
    """An anchored pattern spelled with the project root: it selects below the root.

    The project-relative reading of the whole body is kept too, as it is
    harmless when git finds nothing for it.
    """
    segments = remainder.split("/")
    if not remainder or not _recursive_segments_are_whole(segments) or "" in segments[:-1]:
        return None
    if _without_leading_recursion(segments) == [_ANY_DEPTH]:
        return None
    return [PATHSPEC_MAGIC + remainder, PATHSPEC_MAGIC + body]


def _can_start_above_root(first_segment: str, ancestors: tuple[str, ...]) -> bool:
    """Can ``first_segment`` match a directory name on the way down to the project root?"""
    return any(fnmatch.fnmatchcase(component, first_segment) for component in ancestors)
