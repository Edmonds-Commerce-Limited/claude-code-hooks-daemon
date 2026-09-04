"""Vendor-exception matching, shared by the layout facade and docs QA.

``layout.vendor_exceptions`` names repo-relative path globs that are NOT
vendored even though they sit under a ``layout.vendor_dirs`` name — a
first-party library the project maintains in place inside an otherwise
third-party tree (Plan 00331 Phase 3).

**Why this is a module and not two methods on ``ProjectLayout``.** Both the
facade and ``docs_qa`` need the same answer, and neither may import the
other: ``core.project_layout`` already imports ``docs_qa.corpus``, so a
``docs_qa`` → ``core`` import would close a cycle. Putting the matching here
keeps ONE implementation both sides read, rather than the parallel copies
that made ``layout.vendor_dirs`` inert in the first place. Pure stdlib, so
importing it does not break ``docs_qa``'s deliberate daemon/pydantic
decoupling.

The DIALECT differs from ``vendor_dirs`` deliberately, and the difference is
the whole reason both keys can coexist:

- a ``vendor_dirs`` entry is a directory NAME, a convention that holds
  wherever it appears (``node_modules`` is vendored at any depth);
- a ``vendor_exceptions`` entry is a repo-relative PATH, because the thing it
  names is specific — there is exactly one ``infra/roles/our-own-role``, and
  a bare basename would wrongly re-include every directory sharing it.
"""

from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatch

_SUBTREE_SUFFIX = "/**"


def _is_under(path: str, root: str) -> bool:
    """True when ``path`` IS ``root`` or lives beneath it.

    Segment-aware, so ``ours-vendored`` is not treated as living under
    ``ours`` the way a bare ``startswith`` would.
    """
    path_norm = path.strip("/")
    root_norm = root.strip("/")
    if not root_norm:
        return True
    return path_norm == root_norm or path_norm.startswith(root_norm + "/")


def matches_vendor_exception(rel_path: str, patterns: Sequence[str]) -> bool:
    """Whether ``rel_path`` is carved out of the vendor set by an exception.

    A trailing ``/**`` covers the directory it names as well as everything
    beneath it. That extra clause is load-bearing: a bare ``fnmatch`` of
    ``infra/roles/ours/**`` does not match ``infra/roles/ours`` itself, so a
    file sitting directly in the exception directory would stay hidden — the
    surprising half of the gitignore convention.

    Args:
        rel_path: Repository-relative path (leading/trailing slashes ignored).
        patterns: ``layout.vendor_exceptions`` entries.

    Returns:
        True when any pattern covers the path.
    """
    path = rel_path.strip("/")
    for pattern in patterns:
        if fnmatch(path, pattern):
            return True
        if pattern.endswith(_SUBTREE_SUFFIX) and _is_under(path, pattern[: -len(_SUBTREE_SUFFIX)]):
            return True
    return False


def _literal_prefix(pattern: str) -> str:
    """The leading path segments of ``pattern`` before its first wildcard.

    ``infra/roles/ours/**`` → ``infra/roles/ours``; ``**/ours/**`` → ``""``.
    An empty result means the pattern could match beneath ANY directory.
    """
    head, _, _ = pattern.partition("*")
    if head.endswith("/"):
        return head.strip("/")
    # A wildcard mid-segment (`ours-*/lib/**`) makes that whole segment
    # uncertain, so it cannot count towards the literal prefix.
    return head.rsplit("/", 1)[0].strip("/") if "/" in head else ""


def may_contain_vendor_exception(rel_dir: str, patterns: Sequence[str]) -> bool:
    """Whether an exception could live at or beneath ``rel_dir``.

    The prune-safety question. A walker that prunes a vendored directory out
    of ``os.walk`` never descends into it, so an exception beneath it becomes
    unreachable and the project's own code stays invisible — exactly why git
    cannot re-include a file whose parent directory is excluded. A pruning
    walker must ask this BEFORE pruning.

    Conservative where it cannot prove safety: a pattern with a leading
    wildcard has no literal prefix and could match anywhere, so nothing is
    prunable. Over-descending costs time; over-pruning silently hides
    first-party code, and only one of those failures announces itself. A
    project that wants the pruning back writes an anchored path.

    Args:
        rel_dir: Repository-relative directory path. ``""`` is the repository
            root, which can always contain an exception — reading it as
            prunable would stop a walk before it started.
        patterns: ``layout.vendor_exceptions`` entries.

    Returns:
        True when ``rel_dir`` must not be pruned.
    """
    if not patterns:
        return False
    candidate = rel_dir.strip("/")
    for pattern in patterns:
        prefix = _literal_prefix(pattern)
        if not prefix:
            return True
        # Either direction counts: an ANCESTOR of the exception must be
        # descended to reach it, and a DESCENDANT of it is itself first-party.
        if _is_under(candidate, prefix) or _is_under(prefix, candidate):
            return True
    return False
