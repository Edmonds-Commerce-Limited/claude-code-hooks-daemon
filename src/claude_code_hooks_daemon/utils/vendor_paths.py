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

from collections.abc import Iterable, Sequence
from fnmatch import fnmatch
from typing import Final

_SUBTREE_SUFFIX = "/**"

#: Written in an exclusion list to mean "whatever this project considers
#: vendored" (Plan 00331 Phase 2). Resolved as a PREDICATE REFERENCE, not a
#: glob expansion: expanding it would copy the vendor NAMES into each list —
#: the distributed source of truth again, one indirection later — and could
#: not express an exception without negation syntax and a cross-key
#: precedence rule. A reference has neither problem.
#:
#: Honoured by :func:`~utils.path_exclusion.handler_excludes_path` and so by
#: ``daemon.exclude_paths`` and every per-handler ``exclude_paths``.
#:
#: Deliberately NOT wired into ``documentation.qa.scope_exclude_globs``: docs
#: QA already skips every vendored path by its own policy, so the token would
#: be inert there. A test asserting otherwise passed on the FIRST run without
#: any token support at all, which is how the redundancy was caught —
#: shipping it would have been config surface that does nothing.
VENDOR_DIRS_TOKEN: Final[str] = "{vendor-dirs}"


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


def is_vendored_path(
    rel_path: str, vendor_dirs: Iterable[str], vendor_exceptions: Sequence[str] = ()
) -> bool:
    """The single vendor question, in plain values.

    A path is vendored when any of its segments NAMES a vendored directory
    and it is not carved out by an exception.
    ``ProjectLayout.is_vendored_path`` delegates here so the facade and every
    plain-values caller give the same answer rather than each deriving one --
    the parallel-copies failure this plan exists to end.

    Args:
        rel_path: Repository-relative path.
        vendor_dirs: Effective vendored directory NAMES.
        vendor_exceptions: Repo-relative carve-out globs.

    Returns:
        True when the path should be treated as third-party content.
    """
    names = set(vendor_dirs)
    parts = tuple(part for part in rel_path.split("/") if part and part != ".")
    if not any(part in names for part in parts):
        return False
    return not matches_vendor_exception(rel_path, vendor_exceptions)


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
