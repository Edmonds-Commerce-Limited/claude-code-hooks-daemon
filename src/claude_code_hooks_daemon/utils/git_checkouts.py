"""Which git checkout a path belongs to, read from git's own on-disk markers.

Ledger 00474 N264: a sub-agent's edits landed in another branch's worktree.
Judging that needs one fact per path -- the working tree it sits in -- and the
fact must be the one git holds, not a guess from directory names: worktrees
nest (``untracked/worktrees/X`` lives INSIDE the main working tree), so a
string prefix attributes a worktree's file to the main tree.

Git marks every checkout's root with a ``.git`` entry, and the NEAREST one above
a path is the innermost checkout containing it:

* a ``.git`` directory is a main working tree (its own common dir);
* a ``.git`` file holds ``gitdir: <path>``; when that gitdir carries a
  ``commondir`` file it is a LINKED worktree of the repository that file
  names, otherwise (a submodule, a ``--separate-git-dir`` clone) it is a main
  checkout whose common dir is the gitdir itself.

Two paths are in the same repository exactly when their checkouts share a
``common_dir``. A filesystem probe only, never a subprocess: the answer is a
handful of ``stat`` calls and one small read, so it is cheap enough for every
Write/Edit of a session. A path in no repository is ``None``; a marker that
cannot be read or parsed raises :class:`CheckoutUndecidableError`, because that
is not "no repository" and callers decide what undecidable means for them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_GIT_ENTRY: Final[str] = ".git"
_GITDIR_PREFIX: Final[str] = "gitdir:"
_COMMONDIR_FILE: Final[str] = "commondir"


@dataclass(frozen=True)
class Checkout:
    """One working tree of a repository, every path symlink-resolved."""

    root: Path
    common_dir: Path
    linked: bool


class CheckoutUndecidableError(Exception):
    """A git marker exists but cannot be read or parsed, or the path cannot be resolved."""


def enclosing_checkout(path: str | os.PathLike[str]) -> Checkout | None:
    """The innermost checkout ``path`` sits in, or ``None`` when it is in no repository.

    ``path`` need not exist (a Write creates it): the nearest existing ancestor
    carries the answer.

    Raises:
        CheckoutUndecidableError: The path cannot be resolved, or the nearest
            ``.git`` marker cannot be read or parsed.
    """
    try:
        resolved = Path(os.path.realpath(path))
    except (OSError, ValueError) as exc:
        raise CheckoutUndecidableError(f"cannot resolve {path!r}: {exc}") from exc
    for candidate in (resolved, *resolved.parents):
        marker = candidate / _GIT_ENTRY
        if marker.is_dir():
            return Checkout(root=candidate, common_dir=Path(os.path.realpath(marker)), linked=False)
        if marker.is_file():
            return _checkout_from_git_file(candidate, marker)
    return None


def _read_marker(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise CheckoutUndecidableError(f"cannot read {path}: {exc}") from exc


def _checkout_from_git_file(root: Path, marker: Path) -> Checkout:
    """Parse a ``.git`` FILE: a linked worktree, a submodule or a separate git dir."""
    target = next(
        (
            line.strip()[len(_GITDIR_PREFIX) :].strip()
            for line in _read_marker(marker).splitlines()
            if line.strip().startswith(_GITDIR_PREFIX)
        ),
        "",
    )
    if not target:
        raise CheckoutUndecidableError(f"no gitdir line in {marker}")
    gitdir = Path(os.path.realpath(root / target))
    if not gitdir.is_dir():
        raise CheckoutUndecidableError(f"gitdir {gitdir} named by {marker} is missing")
    commondir_file = gitdir / _COMMONDIR_FILE
    if not commondir_file.is_file():
        return Checkout(root=root, common_dir=gitdir, linked=False)
    common = _read_marker(commondir_file).strip()
    if not common:
        raise CheckoutUndecidableError(f"{commondir_file} is empty")
    return Checkout(root=root, common_dir=Path(os.path.realpath(gitdir / common)), linked=True)
