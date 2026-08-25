"""Place a project's git-ignored local files into a fresh worktree (Plan 00267).

A fresh worktree is a clean checkout, so the git-ignored files that make the
main checkout work are absent from it. This module puts a project's configured
:class:`~claude_code_hooks_daemon.core.worktree_seed.SeedEntry` list in place,
either as a **relative symlink** back to the canonical file or as an
independent **copy**.

Validation and placement are split into two functions on purpose.
``git worktree add`` runs BETWEEN them, so a content error must surface while
there is still nothing to clean up: a half-seeded worktree is worse than an
unseeded one, because the agent working inside it cannot tell which of its
files are missing.

**Symlinks are always relative.** An absolute target dangles the moment the
same tree is viewed at a different prefix — a host at ``/home/user/project``
and a container at ``/workspace`` sharing one bind mount, a configuration this
project explicitly supports. A dangling link is strictly worse than an absent
file: most loaders raise on it rather than treating it as absent. A relative
target resolves under either prefix.

**The two modes trade off differently and neither is safe by accident.** A
symlink keeps the main checkout as the single source of truth, but a write from
INSIDE the worktree flows back through the link and mutates the canonical file.
A copy is isolated, so a worktree agent can overwrite it harmlessly, but it
drifts from the original and costs disk for a large directory. The project
chooses per entry; this module only enforces the choice.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from claude_code_hooks_daemon.core.worktree_seed import SEED_MODE_SYMLINK, SeedEntry

logger = logging.getLogger(__name__)

_PARENT_TRAVERSAL = ".."


class WorktreeSeedError(RuntimeError):
    """A configured seed entry cannot be honoured.

    Raised by :func:`validate_seed_sources` BEFORE the worktree is created, so
    creation is abandoned rather than producing a partially-seeded worktree.
    This is the FAIL FAST half of the module's contract: a *shape* error in the
    config is warned about and skipped during parsing, but a well-formed entry
    naming a path that is absent or unsafe is a clear intention the daemon
    cannot fulfil, and proceeding would hand back a worktree quietly missing
    the files its agent needs.
    """


def _describe_problem(root: Path, entry: SeedEntry) -> str | None:
    """Return why ``entry`` cannot be seeded from ``root``, or ``None`` if it can."""
    candidate = Path(entry.path)
    if candidate.is_absolute():
        return f"{entry.path!r}: must be relative to the repository root, not absolute"
    if _PARENT_TRAVERSAL in candidate.parts:
        return f"{entry.path!r}: must not traverse upwards with {_PARENT_TRAVERSAL!r}"

    source = root / candidate
    if not source.exists():
        return f"{entry.path!r}: no such file or directory at the repository root"

    # The checks above bound where a link is WRITTEN. This bounds where it
    # POINTS: a path traversing a symlinked directory component inside the repo
    # has no '..' and is not absolute, yet can still resolve outside the tree.
    resolved = source.resolve()
    if not resolved.is_relative_to(root.resolve()):
        return f"{entry.path!r}: resolves to {resolved}, outside the repository root"

    if not source.is_file() and not source.is_dir():
        return f"{entry.path!r}: is neither a regular file nor a directory"

    return None


def validate_seed_sources(root: Path, entries: list[SeedEntry]) -> None:
    """Check every entry can be seeded, raising before any worktree exists.

    Args:
        root: The main checkout's repository root, where sources live.
        entries: Validated-by-shape entries from the project's config.

    Raises:
        WorktreeSeedError: if any entry is unsafe, absent, or of an
            unsupported type. EVERY offending entry is named in one message —
            reporting only the first would make fixing a misconfigured list an
            iterative guessing game.
    """
    problems = [problem for entry in entries if (problem := _describe_problem(root, entry))]
    if problems:
        raise WorktreeSeedError(
            "Cannot seed worktree — "
            f"{len(problems)} configured entr{'y is' if len(problems) == 1 else 'ies are'} "
            "unusable:\n  " + "\n  ".join(problems)
        )


def _place(source: Path, dest: Path, mode: str) -> None:
    """Put ``source`` at ``dest`` using ``mode``; the destination must not exist."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    if mode == SEED_MODE_SYMLINK:
        # Relative to the LINK's directory, so the pair survives the whole tree
        # being viewed at a different absolute prefix.
        dest.symlink_to(os.path.relpath(source, dest.parent))
    elif source.is_dir():
        shutil.copytree(source, dest)
    else:
        shutil.copy2(source, dest)


def seed_worktree(root: Path, worktree: Path, entries: list[SeedEntry]) -> list[Path]:
    """Place each entry into ``worktree``, skipping destinations already present.

    Call :func:`validate_seed_sources` first — this function assumes its
    entries are already known to be safe and present.

    An existing destination is never overwritten. The check tests
    ``is_symlink()`` before ``exists()`` because ``exists()`` follows links and
    is therefore False for a *dangling* one: checking only existence would
    silently clobber a broken link the worktree may have been given
    deliberately.

    Args:
        root: The main checkout's repository root.
        worktree: The freshly-created worktree directory.
        entries: The entries to place, in configured order.

    Returns:
        The destinations actually created, in the order placed. A skipped
        destination is absent from this list.
    """
    placed: list[Path] = []
    for entry in entries:
        source = root / entry.path
        dest = worktree / entry.path

        if dest.is_symlink() or dest.exists():
            logger.debug(
                "worktree seed: %s already exists in the worktree; left untouched", entry.path
            )
            continue

        _place(source, dest, entry.mode)
        placed.append(dest)

    if placed:
        logger.info(
            "worktree seed: placed %d entr%s into %s",
            len(placed),
            "y" if len(placed) == 1 else "ies",
            worktree,
        )
    return placed
