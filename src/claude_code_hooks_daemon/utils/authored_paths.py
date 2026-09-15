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
