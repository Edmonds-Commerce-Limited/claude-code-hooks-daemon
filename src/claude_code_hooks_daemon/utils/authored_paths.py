"""Resolving a path an AUTHOR wrote in a document (Plan 00412).

The single place the daemon answers "does this relative target exist?" for a
path it did not choose itself — a markdown link, a path quoted in a plan.

:meth:`pathlib.Path.exists` stats the path exactly as written, which makes
``..`` a FILESYSTEM operation: every directory along the way has to exist for
the answer to be about the target at all. So::

    (Path("CLAUDE/Security") / "../Routine/x.md").exists()

is False whenever ``CLAUDE/Security/`` does not exist yet — which is precisely
the state of the first document written into a new directory, with the target
sitting on disk the whole time. In the edit-time docs gate a new dead link is
BLOCK severity, so that write was denied and no retry could succeed: the
directory only comes into being by the write being allowed.

Normalising ``..`` lexically first is not a workaround for that; it is the more
faithful answer. A markdown renderer resolves a link by text, never by
following the filesystem, so the lexical result is the one a reader of the
rendered document will actually experience. The two readings differ only when a
symlink sits on the path, and there the renderer's answer is the one a docs
check is trying to predict.

Enforced by ``scripts/qa/check_authored_path_stat.py``, which fails the build
on a stat predicate applied to a join anywhere in the trees that resolve
authored paths.
"""

from __future__ import annotations

import os
from pathlib import Path


def authored_path(base: Path, target: str | Path) -> Path:
    """``target``, written relative to ``base``, normalised LEXICALLY.

    No filesystem access at all: ``..`` is resolved by text, so no directory
    along the way has to exist and no symlink is followed.

    Args:
        base: The directory ``target`` is written relative to.
        target: The path as the author wrote it.

    Returns:
        The normalised path. Nothing is asserted about it existing, or about
        it staying under ``base`` — see :func:`contained_authored_path` for
        the second question.
    """
    return Path(os.path.normpath(base / target))


def contained_authored_path(base: Path, target: str | Path) -> Path | None:
    """``target`` resolved, but only when the result stays inside ``base``.

    A DIFFERENT question from :func:`authored_path_exists`, and the one to ask
    before OPENING a path a document named. Normalising makes
    ``src/../../etc/passwd`` resolve faithfully to a real file; that is not the
    same as it being a file the daemon may read. Reading it would make the
    daemon a content oracle over anything the filesystem can reach, and
    ``secret_file_guard`` cannot help — that guard judges the path an AGENT
    names, and nothing an agent typed names the file when the daemon follows a
    marker inside a document.

    Three vectors escape ``base``, and they need two different tests:

    - a ``..`` hop, and an ABSOLUTE target (which discards ``base`` entirely,
      by pathlib's own rule) — both caught lexically;
    - a SYMLINK pointing out, caught only by resolving.

    Resolving is right here and wrong in :func:`authored_path_exists`, which
    stays lexical on purpose: that function predicts what a markdown renderer
    will show a reader, and a renderer resolves a link by text. This one
    predicts where an ``open()`` will land, and ``open()`` follows the link.
    Same input, two correct answers, because the questions differ.

    Args:
        base: The directory the result must stay inside — normally the
            repository root.
        target: The path as the author wrote it.

    Returns:
        The normalised path, or ``None`` when it escapes ``base``. A contained
        path that does not EXIST is still returned: containment is about where
        the path lands, and folding the two answers together would report an
        escape as a missing file.
    """
    candidate = authored_path(base, target)
    if not candidate.is_relative_to(Path(os.path.normpath(base))):
        return None
    # `base` itself may be reached through a symlink (a worktree, a container
    # mount), so its real path is the one to compare against -- measuring a
    # resolved candidate against an unresolved base would refuse every file in
    # such a checkout. `strict=False` keeps a not-yet-existing target
    # answerable: it resolves the parts that do exist.
    if not candidate.resolve(strict=False).is_relative_to(base.resolve(strict=False)):
        return None
    return candidate


def authored_path_exists(base: Path, target: str) -> bool:
    """Whether ``target``, written relative to ``base``, names something on disk.

    Args:
        base: The directory ``target`` is written relative to — the containing
            document's folder, or the repository root.
        target: The path as the author wrote it. May contain ``..``, may be
            absolute (in which case ``base`` is ignored, as pathlib does).

    Returns:
        True when the normalised path names an existing file or directory.
        A genuine dead link stays False: ``..`` is resolved, not discarded.
    """
    return Path(os.path.normpath(base / target)).exists()
