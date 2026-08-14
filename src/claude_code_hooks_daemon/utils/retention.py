"""Shared disk-usage retention primitives (Plan 00181).

Single source of truth for bounding the daemon's untracked writers. Before this
module the daemon had NO retention primitive at all -- every append-only log,
per-session sidecar, and transcript archive grew without bound. Two primitives
live here so every writer bounds itself identically:

* :func:`cap_log_file` -- front-truncate an append-only line log to a byte cap,
  keeping the NEWEST whole lines (drops the partial first line after the seek).
* :func:`prune_directory` -- bound a directory to a max count and/or max age
  (newest kept), never touching a protected path (e.g. the current session's
  own file).

Both are **best-effort housekeeping**: a missing file/dir is a no-op, and an IO
error on an individual entry is logged and skipped -- retention must never raise
into (and so break) the handler that called it. This is deliberate, explicit
error handling, not silent suppression: every failure is logged.

Defaults are NOT defined here -- callers pass explicit byte/count/age budgets
(sourced from config) so this module stays free of magic values and policy.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Collection
from pathlib import Path

logger = logging.getLogger(__name__)


def cap_log_file(path: Path, *, max_bytes: int, retain_bytes: int | None = None) -> bool:
    """Front-truncate an append-only line log so it stays within ``max_bytes``.

    When the file exceeds ``max_bytes`` it is rewritten to keep the most recent
    whole lines fitting in ``retain_bytes`` (default ``max_bytes``), by seeking to
    the tail and dropping the partial first line. Pass ``retain_bytes`` **below**
    ``max_bytes`` to leave headroom so a frequently-appended log is not rewritten
    on every single write once it reaches the ceiling (hysteresis).

    Returns ``True`` when it trimmed, ``False`` when the file was already within
    budget, missing, or could not be read/written. A single line longer than the
    retain budget degrades to keeping the last ``retain_bytes`` bytes (documented
    edge behaviour) rather than emptying the file.
    """
    retain = max_bytes if retain_bytes is None else retain_bytes
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("retention: cannot stat %s: %s", path, exc)
        return False
    if size <= max_bytes:
        return False
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, size - retain))
            tail = handle.read()
        newline = tail.find(b"\n")
        kept = tail[newline + 1 :] if newline != -1 else tail
        tmp = path.with_name(path.name + ".retain.tmp")
        tmp.write_bytes(kept)
        # Plan 00239: the replace makes the log inherit the TEMP file's mode, i.e.
        # whatever the umask produced — so without this the first trim silently
        # re-opens the permissions of a log created owner-only on purpose
        # (verdicts.jsonl, stop-events.jsonl). Copy the log's own mode across.
        shutil.copymode(path, tmp)
        tmp.replace(path)
        return True
    except OSError as exc:
        logger.warning("retention: cannot trim %s: %s", path, exc)
        return False


def prune_directory(
    directory: Path,
    *,
    pattern: str = "*",
    max_count: int | None = None,
    max_age_seconds: float | None = None,
    now: float,
    protect: Collection[Path] = (),
) -> list[Path]:
    """Delete files in ``directory`` matching ``pattern`` that exceed the budget.

    A file is deleted when it is NOT protected and it is excess by ANY configured
    criterion:

    * ``max_count`` -- it is not among the newest ``max_count`` files (by mtime);
    * ``max_age_seconds`` -- ``now - mtime`` exceeds ``max_age_seconds``.

    With neither criterion set, nothing is deleted. ``protect`` paths (resolved)
    are never deleted -- pass the current session's own file(s). A missing
    directory is a no-op. Per-file IO errors are logged and skipped. Returns the
    list of paths actually deleted.
    """
    if max_count is None and max_age_seconds is None:
        return []
    try:
        entries = [p for p in directory.glob(pattern) if p.is_file()]
    except OSError as exc:
        logger.warning("retention: cannot list %s: %s", directory, exc)
        return []

    protected = {_resolve(p) for p in protect}
    dated: list[tuple[float, Path]] = []
    for entry in entries:
        try:
            mtime = entry.stat().st_mtime
        except OSError as exc:
            logger.warning("retention: cannot stat %s: %s", entry, exc)
            continue
        dated.append((mtime, entry))

    # Newest first, so index >= max_count marks the count-excess tail.
    dated.sort(key=lambda item: item[0], reverse=True)

    deleted: list[Path] = []
    for index, (mtime, entry) in enumerate(dated):
        if _resolve(entry) in protected:
            continue
        count_excess = max_count is not None and index >= max_count
        age_excess = max_age_seconds is not None and (now - mtime) > max_age_seconds
        if not (count_excess or age_excess):
            continue
        try:
            entry.unlink()
        except OSError as exc:
            logger.warning("retention: cannot delete %s: %s", entry, exc)
            continue
        deleted.append(entry)
    return deleted


def _resolve(path: Path) -> Path:
    """Best-effort absolute resolution for protected-path comparison."""
    try:
        return path.resolve()
    except OSError:
        return path
