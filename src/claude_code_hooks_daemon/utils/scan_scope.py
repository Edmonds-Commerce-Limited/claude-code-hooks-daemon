"""Scope helpers shared by the QA checks that walk the tree (00466 N26).

Two rules every walker follows:

- An exclusion by directory NAME is judged on the path's components BELOW the
  scan root, never on its absolute path. Every agent worktree lives under
  ``untracked/worktrees/``, so an absolute-path test for ``untracked`` or
  ``worktrees`` excludes the whole checkout.
- A check that examined nothing, while there was something to examine, has not
  passed. It reports a failure instead, so a broken discovery cannot look like
  a clean tree.
"""

from __future__ import annotations

from pathlib import Path


def relative_parts(path: Path, root: Path) -> tuple[str, ...]:
    """``path``'s components below ``root``, for matching directory names.

    A relative ``path`` is taken as already relative to the root. Both sides
    are resolved first, so a symlinked root still matches. A path outside the
    root keeps its own components without the filesystem anchor: it cannot be
    rescued, but it must not pick up a stray match on ``/``.
    """
    if not path.is_absolute():
        return path.parts
    if path.is_relative_to(root):
        return path.relative_to(root).parts
    resolved = path.resolve()
    resolved_root = root.resolve()
    if resolved.is_relative_to(resolved_root):
        return resolved.relative_to(resolved_root).parts
    return resolved.parts[1:]


def vacuous_scan_failure(*, examined: int, candidates: int, noun: str) -> str | None:
    """A failure message when a scan examined none of its candidates, else None.

    Args:
        examined: How many items the check actually examined.
        candidates: How many items its discovery found before exclusions.
        noun: What the items are, for the message (``"files"``).

    Returns:
        None for a scan that examined something, or that genuinely had
        nothing to examine; otherwise a message naming the gap.
    """
    if examined or not candidates:
        return None
    return (
        f"examined 0 of {candidates} {noun}: the discovery or its exclusions "
        "are broken, so this is not a pass"
    )
